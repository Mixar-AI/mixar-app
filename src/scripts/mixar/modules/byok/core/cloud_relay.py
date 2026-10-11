# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Execute a backend ``llm.request`` that needs a key kept on this computer.

The backend holds no BYOK key: it builds the provider request with a
placeholder and sends it here with ``credential: {"provider": ...}``. This
module adds the real key and performs the call. Trust model — this side
re-checks everything before a key leaves the keychain:

- ``https`` to the provider's fixed host and path prefix only
  (``CLOUD_RELAY_TARGETS``, the same table the backend enforces), default
  port, no userinfo/fragment, no ``key=`` query parameter, GET or POST;
- every credential header the request arrived with is dropped and the
  provider's own auth header is set from the keychain (``key_vault``) or, for
  Codex, from the Codex CLI login (``codex_cli_login``);
- redirects are never followed, request/response bytes are capped, and
  response headers are allowlisted.

``credential.provider == "local"`` adds the local server's bearer token (a
custom server's from the keychain, else the Mixar-managed server's from its
manifest) and hands the request to the LOCAL relay, which keeps its own
loopback/private-network checks.

Results follow ``local_models/core/relay.py``: ``respond()`` is called once
with ``{"status_code", "headers", "body"}`` (any HTTP status) or
``{"error": {"code", "message"}}``. Messages never contain key material.
Pure stdlib, blocking — run on a worker thread. No bpy imports.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional, Tuple

from mixar.config.logging_config import get_logger

from ..constants import (
    CLOUD_RELAY_ALLOWED_RESPONSE_HEADERS,
    CLOUD_RELAY_MAX_REQUEST_BYTES,
    CLOUD_RELAY_MAX_RESPONSE_BYTES,
    CLOUD_RELAY_STRIPPED_REQUEST_HEADERS,
    CLOUD_RELAY_TARGETS,
    CLOUD_RELAY_TIMEOUT_S,
)
from . import codex_cli_login, key_vault

logger = get_logger(__name__)

_PROVIDER_NAMES = {
    "anthropic": "Anthropic", "openai": "OpenAI", "gemini": "Google Gemini",
    "fugu": "Sakana Fugu", "kimi": "Moonshot Kimi", "openrouter": "OpenRouter",
    "local": "your local server",
}


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """A 3xx passes through as a plain result; a key never follows it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


# Test seam.
_urlopen = urllib.request.build_opener(_RefuseRedirects()).open


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def target_allowed(provider: str, url: str, method: str) -> bool:
    """Mirror of the backend's ``device_key_relay.target_allowed``."""
    target = CLOUD_RELAY_TARGETS.get(provider)
    if target is None or str(method).upper() not in ("GET", "POST"):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host, prefix = target
    if parts.scheme != "https" or (parts.hostname or "").lower() != host:
        return False
    if port not in (None, 443) or parts.username is not None or parts.fragment:
        return False
    if not parts.path.startswith(prefix) or ".." in parts.path:
        return False
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    return not any(k.lower() == "key" for k, _ in query)


def _auth_headers(provider: str) -> Tuple[Optional[dict], Optional[dict]]:
    """``(headers, None)`` to add, or ``(None, error_marker)``."""
    if provider == "codex":
        try:
            access, account = codex_cli_login.read()
        except codex_cli_login.CodexLoginError as e:
            return None, _error("relay_no_key", str(e))
        return {"Authorization": f"Bearer {access}", "chatgpt-account-id": account}, None
    key = key_vault.get_key(provider)
    if not key:
        name = _PROVIDER_NAMES.get(provider, provider)
        return None, _error(
            "relay_no_key",
            f"No {name} API key is saved on this computer for this account — "
            "open AI Provider Settings and save it again.",
        )
    if provider == "anthropic":
        return {"x-api-key": key}, None
    if provider == "gemini":
        return {"x-goog-api-key": key}, None
    return {"Authorization": f"Bearer {key}"}, None


def _forwarded_headers(headers) -> dict:
    if not isinstance(headers, dict):
        return {}
    return {
        str(k): str(v) for k, v in headers.items()
        if str(k).lower() not in CLOUD_RELAY_STRIPPED_REQUEST_HEADERS
        and not str(k).lower().startswith(("x-forwarded-", "proxy-"))
    }


def _managed_server_token() -> str:
    """The Mixar-managed llama-server's API token (kept in its manifest)."""
    try:
        from mixar.modules.local_models.core import manifest
        return manifest.get_api_token() or ""
    except Exception:  # noqa: BLE001
        return ""


def _handle_local(params: dict, respond: Callable[[dict], None]) -> None:
    from mixar.modules.local_models.core.relay import handle_llm_request

    headers = {
        k: v for k, v in (params.get("headers") or {}).items()
        if str(k).lower() != "authorization"
    }
    bearer = key_vault.get_key("local") or _managed_server_token()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    local_params = {k: v for k, v in params.items() if k != "credential"}
    handle_llm_request({**local_params, "headers": headers}, respond)


def handle_credential_request(params: dict, respond: Callable[[dict], None]) -> None:
    """Execute one ``llm.request`` that carries ``credential.provider``."""
    credential = params.get("credential")
    provider = credential.get("provider") if isinstance(credential, dict) else None
    if not isinstance(provider, str):
        respond(_error("relay_denied", "malformed credential"))
        return
    if provider == "local":
        _handle_local(params, respond)
        return

    url = params.get("url")
    method = str(params.get("method") or "").upper()
    if not isinstance(url, str) or not target_allowed(provider, url, method):
        logger.warning("BYOK relay refused a %s target for %s", method or "?", provider)
        respond(_error("relay_denied", "target is not this provider's API"))
        return

    body = params.get("body")
    if isinstance(body, str):
        body = body.encode("utf-8")
    elif body is None:
        body = b""
    elif not isinstance(body, (bytes, bytearray)):
        respond(_error("relay_denied", "body must be a string"))
        return
    if len(body) > CLOUD_RELAY_MAX_REQUEST_BYTES:
        respond(_error("relay_request_too_large", "request body is too large"))
        return

    auth, denial = _auth_headers(provider)
    if denial is not None:
        respond(denial)
        return
    headers = {**_forwarded_headers(params.get("headers")), **auth}
    request = urllib.request.Request(
        url,
        data=bytes(body) if method == "POST" else None,
        headers=headers,
        method=method,
    )
    try:
        response = _urlopen(request, timeout=CLOUD_RELAY_TIMEOUT_S)
    except urllib.error.HTTPError as http_error:
        response = http_error  # provider status passes through to the SDK
    except Exception as exc:  # noqa: BLE001 — never echo the request
        logger.warning("BYOK relay to %s failed: %s", provider, exc.__class__.__name__)
        respond(_error("relay_transport", f"could not reach {provider}: {exc.__class__.__name__}"))
        return

    try:
        raw = response.read(CLOUD_RELAY_MAX_RESPONSE_BYTES + 1)
        status = getattr(response, "status", None) or response.getcode()
        out_headers = {
            str(k).lower(): str(v) for k, v in response.headers.items()
            if str(k).lower() in CLOUD_RELAY_ALLOWED_RESPONSE_HEADERS
        }
    except Exception as exc:  # noqa: BLE001
        respond(_error("relay_transport", f"error reading response: {exc.__class__.__name__}"))
        return
    finally:
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass
    if len(raw) > CLOUD_RELAY_MAX_RESPONSE_BYTES:
        respond(_error("relay_response_too_large", "provider response is too large"))
        return
    respond({
        "status_code": int(status),
        "headers": out_headers,
        "body": raw.decode("utf-8", errors="replace"),
    })
