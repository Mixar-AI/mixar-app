# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pending public-publish requests awaiting the user's click.

``agent_api.start_game_publish(confirm=True)`` only CREATES a request here.
Nothing in this module approves one: the user approves through the
``mixar.game_publish_approve`` operator, whose ``invoke`` issues a one-time
token into a HIDDEN operator property and shows a confirm dialog; only an
``execute`` carrying that token (i.e. reached from the dialog's button)
claims the request (``ui/operators/game_publish_approval_ops.py``). An agent
script cannot read the token (this module is denied to the sandbox) and
cannot click the dialog. Requests expire after ``APPROVAL_TTL_S``.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
import uuid

APPROVAL_TTL_S = 10 * 60.0
AWAITING, APPROVED, CANCELLED = "awaiting_user_approval", "approved", "cancelled"

_lock = threading.Lock()
_requests: dict[str, dict] = {}


def _expire_locked(now: float) -> None:
    for request in _requests.values():
        if request["state"] == AWAITING and now - request["created"] > APPROVAL_TTL_S:
            request.update(state=CANCELLED, error_code="approval_expired",
                           error="Nobody approved the publish within 10 minutes.", token=None)


def _public(request: dict) -> dict:
    return {"request_id": request["request_id"], "state": request["state"],
            "summary": dict(request["summary"]), "error": request.get("error"),
            "error_code": request.get("error_code"), "created": request["created"]}


def create(summary: dict, payload: dict) -> str:
    """A new pending request; any older pending one is superseded."""
    request_id = uuid.uuid4().hex
    now = time.monotonic()
    with _lock:
        for request in _requests.values():
            if request["state"] == AWAITING:
                request.update(state=CANCELLED, error_code="superseded",
                               error="A newer publish request replaced this one.", token=None)
        _requests[request_id] = {"request_id": request_id, "state": AWAITING, "created": now,
                                 "summary": dict(summary), "payload": dict(payload), "token": None}
        while len(_requests) > 16:
            _requests.pop(next(iter(_requests)))
    return request_id


def get(request_id) -> dict | None:
    with _lock:
        _expire_locked(time.monotonic())
        request = _requests.get(str(request_id or ""))
        return _public(request) if request else None


def pending() -> dict | None:
    """The live pending request, if any."""
    with _lock:
        _expire_locked(time.monotonic())
        for request in reversed(_requests.values()):
            if request["state"] == AWAITING:
                return _public(request)
    return None


def cancel(request_id, reason: str = "Cancelled.", code: str = "cancelled") -> bool:
    """Anyone may cancel (cancelling never publishes)."""
    with _lock:
        request = _requests.get(str(request_id or ""))
        if request is None or request["state"] != AWAITING:
            return False
        request.update(state=CANCELLED, error=reason, error_code=code, token=None)
        return True


def mark_failed(request_id, error: str, code: str) -> None:
    """An approved request whose job could not start."""
    with _lock:
        request = _requests.get(str(request_id or ""))
        if request is not None and request["state"] == APPROVED:
            request.update(state="failed", error=error, error_code=code)


def _issue_token(request_id) -> str:
    """UI operator ``invoke`` only: a fresh one-time token for the dialog."""
    token = secrets.token_hex(16)
    with _lock:
        _expire_locked(time.monotonic())
        request = _requests.get(str(request_id or ""))
        if request is None or request["state"] != AWAITING:
            return ""
        request["token"] = token
    return token


def _claim(request_id, token: str) -> dict | None:
    """UI operator ``execute`` only: approve with the dialog's token and
    return the payload, once. Wrong/missing token, expiry or a second
    claim return None."""
    with _lock:
        _expire_locked(time.monotonic())
        request = _requests.get(str(request_id or ""))
        if (request is None or request["state"] != AWAITING or not token
                or not request.get("token") or not hmac.compare_digest(request["token"], token)):
            return None
        request.update(state=APPROVED, token=None)
        return dict(request["payload"])


def reset_for_tests() -> None:
    with _lock:
        _requests.clear()
