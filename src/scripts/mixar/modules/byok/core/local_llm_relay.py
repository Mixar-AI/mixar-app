# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Proxy a relayed LLM request to the user's local model server.

The backend cannot reach the user's ``localhost``, so for the LOCAL BYOK
provider it ships each OpenAI-format HTTP request over the WebSocket as an
``llm.request`` RPC. This module performs the actual call on the user's machine
and returns the response for the backend to reconstruct.

Security: this makes the Blender client an HTTP client driven by the backend.
To ensure it can never be used as an open proxy to arbitrary hosts, requests
are pinned to the exact endpoint the user approved locally. The backend cannot
change the scheme, host, port, path, or HTTP method, even if it is compromised.
The approved base URL is persisted in the OS credential store so a backend
response is never treated as the trust anchor.

Uses only the standard library (``urllib``) — always present in Blender's
embedded Python, no dependency on bundled ``requests``/``httpx``.
"""

import ipaddress
import json
import socket
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Default ceiling for a single local generation. Kept just under the backend's
# relay timeout so the client returns a real 502 rather than the backend seeing
# a WebSocket timeout first.
_DEFAULT_TIMEOUT = 280.0
_MIN_TIMEOUT = 1.0
_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_MAX_RESPONSE_BYTES = 32 * 1024 * 1024

_CREDENTIAL_SERVICE = "MixarSafeStorage"
_CREDENTIAL_ACCOUNT = "LocalLLMBaseURL"
_approved_base_url: Optional[str] = None
_approval_lock = threading.Lock()

_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)

# Request headers we must NOT forward verbatim — urllib sets its own, and a
# stale Accept-Encoding would make the local server gzip a body urllib won't
# transparently decode.
_ALLOWED_REQUEST_HEADERS = {"accept", "authorization", "content-type"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return 3xx responses to the caller instead of following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect())


def _error_response(status_code: int, message: str) -> Dict[str, Any]:
    """A synthetic OpenAI-style error response the backend SDK understands."""
    body = json.dumps({"error": {"message": message, "type": "mixar_local_relay"}})
    return {
        "status_code": status_code,
        "headers": {"content-type": "application/json"},
        "body": body,
    }


def _is_local_host(host: str) -> bool:
    """True when ``host`` is loopback or an RFC-private address.

    ``localhost`` is allowed by name. Bare IPs are checked directly. Hostnames
    other than localhost are resolved once and every resolved address must be
    private — this both supports LAN-hosted models (e.g. 192.168.x.x) and blocks
    the client being pointed at a public host.
    """
    if not host:
        return False
    if host.lower() in ("localhost", "localhost.localdomain"):
        return True

    def _addr_is_local(addr: str) -> bool:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        return ip.is_loopback or any(ip in network for network in _PRIVATE_NETWORKS)

    # Bare IP literal
    try:
        ipaddress.ip_address(host)
        return _addr_is_local(host)
    except ValueError:
        pass

    # Hostname → resolve; require every resolved address to be local.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    resolved = {info[4][0] for info in infos}
    return bool(resolved) and all(_addr_is_local(addr) for addr in resolved)


def _parse_approved_base_url(base_url: str):
    """Validate a user-entered base URL and return its parsed form."""
    value = (base_url or "").strip().rstrip("/")
    parsed = urlparse(value)
    try:
        parsed.port
    except ValueError:
        return None, "The local server URL has an invalid port."
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None, "Enter a valid URL, e.g. http://localhost:11434."
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None, "The local server URL cannot contain credentials, a query, or a fragment."
    if not _is_local_host(parsed.hostname):
        return None, (
            f"'{parsed.hostname}' is not a loopback or private address. "
            "The local provider only reaches user-approved local model servers."
        )
    return parsed, None


def _normalised_base_url(base_url: str) -> str:
    """Stable value stored locally after validation."""
    return (base_url or "").strip().rstrip("/")


def get_approved_base_url() -> str:
    """Read the user-approved endpoint from local OS credential storage."""
    global _approved_base_url
    with _approval_lock:
        if _approved_base_url is not None:
            return _approved_base_url
        try:
            import keyring

            stored = keyring.get_password(_CREDENTIAL_SERVICE, _CREDENTIAL_ACCOUNT)
        except Exception as e:  # noqa: BLE001 - fail closed if storage is unavailable
            logger.warning("Could not read local LLM endpoint approval: %s", e)
            stored = ""
        parsed, _ = _parse_approved_base_url(stored or "")
        _approved_base_url = _normalised_base_url(stored) if parsed else ""
        return _approved_base_url


def store_approved_base_url(base_url: str) -> tuple[bool, Optional[str]]:
    """Persist a URL the user entered and approved in the local UI."""
    global _approved_base_url
    parsed, error = _parse_approved_base_url(base_url)
    if not parsed:
        return False, error
    value = _normalised_base_url(base_url)
    try:
        import keyring

        keyring.set_password(_CREDENTIAL_SERVICE, _CREDENTIAL_ACCOUNT, value)
    except Exception as e:  # noqa: BLE001 - approval must fail closed
        logger.error("Could not persist local LLM endpoint approval: %s", e)
        return False, "Could not store the local server approval on this device."
    with _approval_lock:
        _approved_base_url = value
    return True, None


def clear_approved_base_url() -> None:
    """Remove the local relay trust anchor after the BYOK config is removed."""
    global _approved_base_url
    try:
        import keyring

        keyring.delete_password(_CREDENTIAL_SERVICE, _CREDENTIAL_ACCOUNT)
    except Exception:
        # Missing entries and unavailable credential stores are both safe: the
        # in-process value is still cleared and future reads fail closed.
        pass
    with _approval_lock:
        _approved_base_url = ""


def _effective_port(parsed) -> int:
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def _expected_chat_path(base_path: str) -> str:
    base_path = (base_path or "").rstrip("/")
    api_path = base_path if base_path.endswith("/v1") else f"{base_path}/v1"
    return f"{api_path}/chat/completions" or "/v1/chat/completions"


def _target_matches_approval(url: str, approved_base_url: str) -> bool:
    """Require the exact Chat Completions endpoint derived from local approval."""
    approved, _ = _parse_approved_base_url(approved_base_url)
    target = urlparse(url or "")
    if not approved or target.scheme not in ("http", "https") or not target.hostname:
        return False
    try:
        target_port = _effective_port(target)
    except ValueError:
        return False
    if target.username or target.password or target.query or target.fragment:
        return False
    return (
        target.scheme == approved.scheme
        and target.hostname.lower() == approved.hostname.lower()
        and target_port == _effective_port(approved)
        and target.path == _expected_chat_path(approved.path)
    )


def _coerce_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT
    return min(_DEFAULT_TIMEOUT, max(_MIN_TIMEOUT, timeout))


def _read_response_body(stream) -> Optional[str]:
    """Read a bounded local-server response, or return None when oversized."""
    raw = stream.read(_MAX_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_RESPONSE_BYTES:
        return None
    return raw.decode("utf-8", errors="replace")


def ping_endpoint(base_url: str, timeout: float = 8.0) -> tuple[bool, Optional[str]]:
    """Check that a local model server is reachable at ``base_url``.

    Runs on the client (which CAN reach its own localhost, unlike the backend),
    so it is the real reachability gate before a local config is saved. Probes
    the OpenAI-compatible ``/v1/models`` endpoint. Returns
    ``(reachable, error_message)`` — ``error_message`` is user-facing on failure.
    """
    parsed, error = _parse_approved_base_url(base_url)
    if not parsed:
        return False, error

    root = f"{parsed.scheme}://{parsed.netloc}"
    models_url = f"{base_url.rstrip('/')}/v1/models" if not base_url.rstrip("/").endswith("/v1") \
        else f"{base_url.rstrip('/')}/models"
    try:
        with _NO_REDIRECT_OPENER.open(models_url, timeout=timeout) as resp:
            # Any HTTP answer (even 404) proves something is listening; a
            # 2xx from /v1/models is the happy path.
            if 200 <= resp.status < 300:
                return True, None
            return True, None
    except urllib.error.HTTPError:
        # Server answered (e.g. 404/401) — it is reachable, which is all we
        # verify here; the model itself is checked at first use.
        return True, None
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        reason = getattr(e, "reason", e)
        return False, f"Could not reach {root} ({reason}). Is your server running?"
    except Exception as e:  # noqa: BLE001
        return False, f"Could not reach {root}: {e}"


def handle_llm_request(params: Dict[str, Any]) -> Dict[str, Any]:
    """Perform a relayed local-LLM HTTP call. Never raises — always returns a
    response dict ``{status_code, headers, body}`` for the backend to rebuild."""
    url = params.get("url") or ""
    method = (params.get("method") or "POST").upper()
    headers = params.get("headers") or {}
    body = params.get("body") or ""
    timeout = _coerce_timeout(params.get("timeout") or _DEFAULT_TIMEOUT)

    parsed = urlparse(url)
    approved_base_url = get_approved_base_url()
    if not approved_base_url:
        return _error_response(
            403,
            "Local LLM relay is not approved on this device. Re-save the local "
            "provider in AI Provider Settings.",
        )
    if method != "POST" or not _target_matches_approval(url, approved_base_url):
        logger.warning("Refusing LLM relay target outside the local approval: %s %s", method, url)
        return _error_response(
            403,
            "Refusing a local LLM request that does not match the endpoint "
            "approved in AI Provider Settings.",
        )

    if isinstance(body, str):
        data = body.encode("utf-8")
    elif isinstance(body, (bytes, bytearray)):
        data = bytes(body)
    else:
        return _error_response(400, "Local LLM request body must be text or bytes.")
    if len(data) > _MAX_REQUEST_BYTES:
        return _error_response(413, "Local LLM request exceeded the 16 MiB limit.")
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in headers.items():
        if key.lower() not in _ALLOWED_REQUEST_HEADERS:
            continue
        req.add_header(key, str(value))

    try:
        with _NO_REDIRECT_OPENER.open(req, timeout=timeout) as resp:
            response_body = _read_response_body(resp)
            if response_body is None:
                return _error_response(502, "Local LLM response exceeded the 32 MiB limit.")
            return {
                "status_code": resp.status,
                "headers": {k: v for k, v in resp.headers.items()},
                "body": response_body,
            }
    except urllib.error.HTTPError as e:
        # A real HTTP error from the local server (e.g. 400 "model doesn't
        # support tools"). Pass its status + body through so the backend SDK
        # surfaces the actual provider error to the agent.
        response_body = _read_response_body(e)
        if response_body is None:
            return _error_response(502, "Local LLM response exceeded the 32 MiB limit.")
        return {
            "status_code": e.code,
            "headers": {k: v for k, v in (e.headers or {}).items()},
            "body": response_body,
        }
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        reason = getattr(e, "reason", e)
        logger.warning("Local LLM unreachable at %s: %s", url, reason)
        return _error_response(
            502,
            f"Could not reach the local LLM at {parsed.scheme}://{parsed.netloc} "
            f"({reason}). Is your local server running?",
        )
    except Exception as e:  # noqa: BLE001 — never raise into the WS loop
        logger.error("Unexpected local LLM relay error: %s", e, exc_info=True)
        return _error_response(500, "The local LLM relay failed unexpectedly.")
