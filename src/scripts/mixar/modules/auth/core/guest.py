# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Guest accounts: a token pair the desktop holds before anyone signs in.

A guest is a real backend account with no credits: the agent runs on the
user's own model key, MCP's free tools work, and every paid route answers
HTTP 403 ``login_required`` (never 401, so nothing refreshes or retries).
Signing in CLAIMS the guest — its BYOK key and chat ownership move to the
account — which is why the guest's refresh token is kept in hand across the
sign-in flow. Wire contract: ``docs/api/frontend/guest-accounts.md`` in the
backend repo; client behaviour: ``docs/modules/guest-accounts.md``.

bpy-free: the HTTP work runs on the auth daemon thread. The WindowManager
mirror (``wm.mixie_chat_is_guest``) is written by the login apply paths.
"""

import json

import requests

from ....config.config import add_config, get_config, get_server_url
from ....config.logging_config import get_logger
from ...common.network import classify_network_error, log_network_failure
from ..utils.constants import AUTH_BASE_URL
from .auth import (
    get_access_token, store_login_token_pair, take_replaced_refresh_token, user_id_from_token,
)
from .device import get_device_id

logger = get_logger(__name__)

# ``data.code`` values of the backend's refusal body.
LOGIN_REQUIRED_CODE = "login_required"
GUEST_RATE_LIMITED_CODE = "guest_rate_limited"
GUEST_DISABLED_CODE = "guest_accounts_disabled"

# ``data.cta``: what fixes the refusal.
CTA_LOGIN = "login"
CTA_LOGIN_OR_BYOK = "login_or_byok"
CTA_FIX_BYOK = "fix_byok"

# User-overlay config key: the stored token pair belongs to a guest. A pair
# that dies (idle sweep, kill switch) is then replaced by a fresh guest
# instead of the "session expired" sign-in flow an account gets.
_SESSION_KEY = "guest_session"

_is_guest = False
_email = ""


def is_guest() -> bool:
    """Whether the current session is a guest's (any thread)."""
    return _is_guest


def email() -> str:
    """The guest's placeholder email, the key its chat archive is filed under."""
    return _email


def mark(guest: bool, address: str = "") -> None:
    """Record what ``/auth/me`` said about the stored pair. Main thread."""
    global _is_guest, _email
    _is_guest = guest
    _email = address if guest else ""
    if bool(get_config().get(_SESSION_KEY, False)) != guest:
        add_config(_SESSION_KEY, guest)


def stored_pair_is_guest() -> bool:
    return bool(get_config().get(_SESSION_KEY, False))


def login_required_fields(body) -> dict:
    """The refusal's ``{code, cta, message, action_label}``, or ``{}``.

    Accepts every shape the refusal travels in: the HTTP body (flat or under
    ``detail``), the JSON-RPC ``-32021`` error's ``data``, and the
    ``login_required`` stream event.
    """
    if not isinstance(body, dict):
        return {}
    inner = body.get("detail") if isinstance(body.get("detail"), dict) else body
    cta = inner.get("data") if isinstance(inner.get("data"), dict) else inner
    code = cta.get("code")
    if code not in (LOGIN_REQUIRED_CODE, GUEST_RATE_LIMITED_CODE):
        return {}
    return {
        "code": code,
        "cta": cta.get("cta") or CTA_LOGIN,
        "message": inner.get("message") or "",
        "action_label": cta.get("action_label") or "",
    }


def _error_body(response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def create_guest_session() -> dict:
    """``POST /auth/guest``: a NEW guest, its pair stored like a login's.

    ``{"success": False, "disabled": True}`` when the backend's kill switch
    is off; the caller then keeps today's signed-out behaviour.
    """
    url = f"{get_server_url()}/{AUTH_BASE_URL}/guest"
    payload = {}
    device_id = get_device_id()
    if device_id:
        payload["device_id"] = device_id
    try:
        from ...common.api.client_version import get_client_version

        version = get_client_version()
        if version:
            payload["client_version"] = version
    except Exception:  # noqa: BLE001 — advisory field
        pass
    try:
        response = requests.post(
            url, data=json.dumps(payload),
            headers={"Content-Type": "application/json", "accept": "application/json"},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        failure = classify_network_error(e, url=url)
        log_network_failure(logger, failure, "Guest session")
        return {"success": False, "message": failure.user_text, "failure_kind": failure.kind}

    if response.status_code in (200, 201):
        data = _error_body(response)
        access_token, refresh_token = data.get("access_token"), data.get("refresh_token")
        if not (access_token and refresh_token):
            return {"success": False, "message": "Incomplete token pair in guest response"}
        stored, storage_error = store_login_token_pair(access_token, refresh_token)
        if not stored:
            return {"success": False, "message": storage_error}
        logger.info("Guest session started")
        return {"success": True}

    body = _error_body(response)
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    code = (detail.get("data") or {}).get("code") if isinstance(detail, dict) else None
    message = detail.get("message") if isinstance(detail, dict) else None
    logger.info("Guest session refused: HTTP %s %s", response.status_code, code or "")
    return {
        "success": False,
        "disabled": code == GUEST_DISABLED_CODE,
        "message": message or f"Guest session failed: {response.status_code}",
    }


def claim_guest(guest_refresh_token: str) -> dict:
    """``POST /auth/guest/claim`` with the signed-in account's bearer.

    400 ``guest_token_invalid`` / 409 ``guest_already_claimed`` mean there is
    nothing to carry over — the sign-in proceeds as a plain one.
    """
    url = f"{get_server_url()}/{AUTH_BASE_URL}/guest/claim"
    try:
        response = requests.post(
            url, data=json.dumps({"guest_refresh_token": guest_refresh_token}),
            headers={
                "Content-Type": "application/json",
                "accept": "application/json",
                "Authorization": f"Bearer {get_access_token()}",
            },
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        failure = classify_network_error(e, url=url)
        log_network_failure(logger, failure, "Guest claim")
        return {"claimed": False}
    body = _error_body(response)
    if response.status_code == 200:
        data = body.get("data") or {}
        logger.info(
            "Guest claimed: byok_moved=%s byok_kept_account=%s",
            data.get("byok_moved"), data.get("byok_kept_account"),
        )
        return {"claimed": bool(data.get("claimed", True)), **data}
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    logger.info(
        "Guest claim skipped: HTTP %s %s", response.status_code,
        (detail.get("data") or {}).get("code") if isinstance(detail, dict) else "",
    )
    return {"claimed": False}


def sign_in(login_fn) -> dict:
    """Run a sign-in flow and claim the guest it replaces.

    The ONE place every login path (the SSO operator, the startup re-login)
    goes through: ``login_fn`` stores the account's pair, after which the
    replaced refresh token — the guest's proof of possession — is claimed
    under the account's bearer. The result gains ``switched_from_guest`` so
    the main-thread apply path can drop the guest socket and reload state,
    plus ``guest_user_id`` / ``byok_moved`` so the device key record the guest
    saved can be re-scoped to the account (``byok.core.key_store.reassign``).
    """
    was_guest = is_guest()
    guest_user_id = user_id_from_token(get_access_token()) if was_guest else None
    result = login_fn()
    if not result.get("success"):
        return result
    guest_refresh = take_replaced_refresh_token()
    if was_guest and guest_refresh:
        claim = claim_guest(guest_refresh)
        result["claimed_guest"] = claim.get("claimed", False)
        # The roles whose key row moved to the account: the key material for
        # them lives on this device under the guest's id (byok key_store).
        result["byok_moved"] = list(claim.get("byok_moved") or [])
        result["guest_user_id"] = guest_user_id
    result["switched_from_guest"] = was_guest
    return result
