# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Codex (ChatGPT subscription) credentials, handled on the desktop.

The Codex CLI's sign-in is the source of truth: ``$CODEX_HOME/auth.json``
(default ``~/.codex/auth.json``, written by ``codex login``). Mixar keeps a
REFERENCE to that file in its credential store (`key_store`), never a copy of
the tokens: before a turn it reads the file, sends ONLY the access token +
ChatGPT account id (the server never sees the file), and when the access
token is near expiry it refreshes and writes the new pair back into the same
file in the CLI's own layout — so Mixar and the CLI stay in step whichever
one refreshed last.

Pure functions here (parsing, claim decoding, expiry, refresh-response
interpretation, file read/write-back) are bpy-free and unit-tested;
`refresh_access_token` is the one network call and runs on a worker thread
only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import tempfile
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Dict, Optional

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ..constants import (
    CODEX_ACCOUNT_ID_CLAIM,
    CODEX_AUTH_CLAIM,
    CODEX_CLIENT_ID,
    CODEX_REFRESH_MARGIN_S,
    CODEX_REFRESH_TIMEOUT_S,
    CODEX_TOKEN_SCOPE,
    CODEX_TOKEN_URL,
    CODEX_USER_AGENT,
)

logger = get_logger(__name__)

# User-facing messages (msgids; the UI translates).
MSG_BUNDLE_INVALID = n_("That is not a valid auth.json — run `codex login` and load the file again.")
MSG_BUNDLE_NO_TOKENS = n_(
    "auth.json has no access or refresh token — run `codex login` and load the file again."
)
MSG_BUNDLE_NO_ACCOUNT = n_(
    "auth.json carries no ChatGPT account id — run `codex login` and load the file again."
)
MSG_SIGN_IN_EXPIRED = n_(
    "Codex sign-in expired — run `codex login` on this computer and try again."
)
MSG_FILE_MISSING = n_(
    "No Codex sign-in found on this computer — run `codex login`, then try again."
)
MSG_FILE_UNREADABLE = n_("Could not read the Codex sign-in file (auth.json).")
MSG_FILE_NOT_WRITABLE = n_(
    "Your Codex sign-in needs renewing but its file (auth.json) is not writable — "
    "fix the file permissions or run `codex login`, then try again."
)
MSG_REFRESH_UNREACHABLE = n_(
    "Could not renew your Codex sign-in — check your connection and try again."
)


class CodexBundleError(ValueError):
    """A pasted/loaded auth.json the client cannot use; `.message` is user-safe."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class CodexCredentials:
    access_token: str
    refresh_token: str
    account_id: str
    id_token: Optional[str] = None


# ---------------------------------------------------------------------------
# JWT claims (base64url payload, no signature check — the server verifies)
# ---------------------------------------------------------------------------

def decode_claims(token: Optional[str]) -> Dict[str, Any]:
    """The payload claims of a JWT, or {} for anything that is not one."""
    if not token or not isinstance(token, str) or token.count(".") != 2:
        return {}
    encoded = token.split(".")[1]
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        claims = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    return claims if isinstance(claims, dict) else {}


def account_id_from_token(token: Optional[str]) -> Optional[str]:
    """``https://api.openai.com/auth`` → ``chatgpt_account_id``."""
    auth_claim = decode_claims(token).get(CODEX_AUTH_CLAIM)
    if not isinstance(auth_claim, dict):
        return None
    value = auth_claim.get(CODEX_ACCOUNT_ID_CLAIM)
    return str(value) if value else None


def token_expiry(token: Optional[str]) -> Optional[float]:
    """The ``exp`` claim as a POSIX timestamp, or None when absent/invalid."""
    expiry = decode_claims(token).get("exp")
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
        return None
    if not math.isfinite(expiry):
        return None
    return float(expiry)


def needs_refresh(token: Optional[str], now: Optional[float] = None,
                  margin_s: float = CODEX_REFRESH_MARGIN_S) -> bool:
    """True when ``exp`` is missing or less than ``margin_s`` away."""
    expiry = token_expiry(token)
    if expiry is None:
        return True
    return expiry - (time.time() if now is None else now) < margin_s


def is_expired(token: Optional[str], now: Optional[float] = None) -> bool:
    """True when the token's ``exp`` is in the past (missing counts as expired)."""
    expiry = token_expiry(token)
    if expiry is None:
        return True
    return expiry <= (time.time() if now is None else now)


# ---------------------------------------------------------------------------
# ~/.codex/auth.json
# ---------------------------------------------------------------------------

def parse_auth_bundle(text: str) -> CodexCredentials:
    """Tokens may be nested under ``"tokens"`` or flat at the top level.

    The account id is ``tokens.account_id`` when present, else the
    ``chatgpt_account_id`` claim of the id_token, else of the access_token.
    Raises `CodexBundleError` with a user-safe message.
    """
    try:
        data = json.loads(text or "")
    except ValueError:
        raise CodexBundleError(MSG_BUNDLE_INVALID) from None
    if not isinstance(data, dict):
        raise CodexBundleError(MSG_BUNDLE_INVALID)
    tokens = data.get("tokens")
    source = tokens if isinstance(tokens, dict) else data

    access_token = _string(source.get("access_token"))
    refresh_token = _string(source.get("refresh_token"))
    id_token = _string(source.get("id_token"))
    if not access_token or not refresh_token:
        raise CodexBundleError(MSG_BUNDLE_NO_TOKENS)

    account_id = (
        _string(source.get("account_id"))
        or account_id_from_token(id_token)
        or account_id_from_token(access_token)
    )
    if not account_id:
        raise CodexBundleError(MSG_BUNDLE_NO_ACCOUNT)
    return CodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=account_id,
        id_token=id_token or None,
    )


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


# ---------------------------------------------------------------------------
# The CLI's file: read by reference, refreshed tokens written back
# ---------------------------------------------------------------------------

def default_auth_path() -> str:
    """``$CODEX_HOME/auth.json``, else ``~/.codex/auth.json`` (the CLI's rule)."""
    home = (os.environ.get("CODEX_HOME") or "").strip()
    base = os.path.expanduser(home) if home else os.path.join(os.path.expanduser("~"), ".codex")
    return os.path.join(base, "auth.json")


def resolve_auth_path(path: Optional[str]) -> str:
    """A user-entered path (empty = the default), expanded."""
    text = (path or "").strip()
    return os.path.expanduser(text) if text else default_auth_path()


def read_auth_file(path: Optional[str]) -> CodexCredentials:
    """Parse the sign-in file at ``path`` (empty = default).

    Raises `CodexBundleError` with a user-safe message: missing file (the
    user ran ``codex logout`` or never logged in), unreadable, or a bundle
    without the tokens the turn needs.
    """
    resolved = resolve_auth_path(path)
    if not os.path.isfile(resolved):
        raise CodexBundleError(MSG_FILE_MISSING)
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        raise CodexBundleError(MSG_FILE_UNREADABLE) from None
    return parse_auth_bundle(text)


def write_back(path: Optional[str], access_token: str, refresh_token: Optional[str] = None,
               id_token: Optional[str] = None) -> bool:
    """Persist renewed tokens INTO the CLI's file, in its own layout.

    Only the token fields (and ``last_refresh``, as the CLI stamps it) change;
    every other key is preserved. Nested ``"tokens"`` or flat, whichever the
    file uses. Written atomically (temp file in the same directory, then
    replace) with owner-only permissions. Returns False when the file is
    gone or not JSON — the sign-in was removed underneath us; nothing is
    created from scratch.
    """
    resolved = resolve_auth_path(path)
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    target = data["tokens"] if isinstance(data.get("tokens"), dict) else data
    target["access_token"] = access_token
    if refresh_token:
        target["refresh_token"] = refresh_token
    if id_token:
        target["id_token"] = id_token
    data["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    directory = os.path.dirname(resolved) or "."
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".auth.json.", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, resolved)
    except OSError:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        logger.warning("Codex auth.json write-back failed")
        return False
    return True


def can_write_back(path: Optional[str]) -> bool:
    """Whether `write_back` can replace the file: the file and its directory
    are writable. Checked BEFORE a refresh grant is spent — the refresh
    endpoint rotates the refresh token, so renewing a sign-in whose file
    cannot keep the new pair would sign the Codex CLI out as well."""
    resolved = resolve_auth_path(path)
    directory = os.path.dirname(resolved) or "."
    return os.access(resolved, os.W_OK) and os.access(directory, os.W_OK)


def fingerprint(refresh_token: Optional[str]) -> Optional[str]:
    """A short digest that identifies a refresh token without storing it:
    how `key_store` remembers WHICH sign-in the server revoked, so a fresh
    ``codex login`` (a different token) clears the "expired" state by itself."""
    if not refresh_token:
        return None
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

@dataclass
class RefreshOutcome:
    """``status``: ``ok`` (tokens renewed), ``revoked`` (400/401/403 — the
    sign-in is gone), ``network`` (unreachable / transient; nothing changed)."""

    status: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    message: Optional[str] = None


def interpret_refresh_response(status_code: Optional[int], body: Any) -> RefreshOutcome:
    """Pure: classify the token endpoint's answer."""
    if status_code is not None and 200 <= status_code < 300:
        payload = body if isinstance(body, dict) else {}
        access_token = _string(payload.get("access_token"))
        if not access_token:
            return RefreshOutcome("network", message=MSG_REFRESH_UNREACHABLE)
        return RefreshOutcome(
            "ok",
            access_token=access_token,
            refresh_token=_string(payload.get("refresh_token")) or None,
        )
    if status_code in (400, 401, 403):
        return RefreshOutcome("revoked", message=MSG_SIGN_IN_EXPIRED)
    return RefreshOutcome("network", message=MSG_REFRESH_UNREACHABLE)


def refresh_access_token(refresh_token: str) -> RefreshOutcome:
    """POST the refresh grant. Worker thread only (10 s budget).

    Never logs the tokens or the response body.
    """
    import requests

    from mixar.modules.common.network import classify_network_error, log_network_failure

    body = {
        "grant_type": "refresh_token",
        "client_id": CODEX_CLIENT_ID,
        "refresh_token": refresh_token,
        "scope": CODEX_TOKEN_SCOPE,
    }
    headers = {"Content-Type": "application/json", "User-Agent": CODEX_USER_AGENT}
    try:
        response = requests.post(
            CODEX_TOKEN_URL, json=body, headers=headers, timeout=CODEX_REFRESH_TIMEOUT_S,
        )
    except requests.exceptions.RequestException as exc:
        failure = classify_network_error(exc, url=CODEX_TOKEN_URL)
        log_network_failure(logger, failure, "Codex token refresh")
        return RefreshOutcome("network", message=failure.user_text)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    outcome = interpret_refresh_response(response.status_code, payload)
    logger.info("Codex token refresh: HTTP %s → %s", response.status_code, outcome.status)
    return outcome
