# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Refresh UI account eligibility off-thread; expiry is monotonic and bounded."""

import threading
import time

_lock = threading.Lock()
_deadline = 0.0
_generation = 0
_refreshing = False
_identity = None
_next_attempt = 0.0
_reason = "starting"


def valid():
    with _lock:
        return time.monotonic() < _deadline


def status():
    with _lock:
        allowed = time.monotonic() < _deadline
        return {"eligible": allowed, "reason": None if allowed else
                ("eligibility_expired" if _reason == "ready" else _reason)}


def invalidate():
    global _deadline, _generation, _reason
    with _lock:
        _deadline = 0.0
        _generation += 1
        _reason = "disabled"


def refresh(context):
    global _refreshing, _identity, _generation, _deadline, _next_attempt, _reason
    identity = (context.get("instance_id"), context.get("backend_url"), context.get("connected"),
                context.get("signed_in"))
    with _lock:
        if identity != _identity:
            _identity, _deadline = identity, 0.0
            _generation += 1
            _reason = "starting" if context.get("signed_in") else "signin_required"
        if (not context.get("connected") or not context.get("signed_in")
                or _refreshing or time.monotonic() < _next_attempt):
            return
        if _deadline-time.monotonic() > 20:
            return
        _refreshing = True
        generation = _generation
        _next_attempt = time.monotonic()+5
    threading.Thread(target=_fetch, args=(dict(context), generation), daemon=True,
                     name="MixarUIEligibility").start()


def _fetch(context, generation):
    global _refreshing, _deadline, _reason
    import requests
    from mixar.modules.auth.core.auth import get_access_token, refresh_access_token
    from mixar.modules.common.network import classify_network_error, log_network_failure
    from mixar.config.logging_config import get_logger
    started = time.monotonic()
    deadline = 0.0
    reason = "backend_unavailable"
    try:
        token = get_access_token()
        if token:
            for attempt in range(2):
                response = requests.get(context["backend_url"].rstrip('/')+"/api/v1/mcp-desktop/eligibility",
                    headers={**context["headers"], "Authorization": "Bearer "+token,
                             "X-Mixar-Instance-Id": context["instance_id"]}, timeout=(3, 5), allow_redirects=False)
                if response.status_code == 401 and attempt == 0 and refresh_access_token().get("success"):
                    token = get_access_token()
                    if token:
                        continue
                break
            reason = {401: "signin_required", 403: "account_unavailable",
                      404: "backend_update_required", 409: "client_update_required",
                      426: "client_update_required"}.get(response.status_code, reason)
            if response.status_code == 200:
                data = response.json()
                if (data.get("eligible") is True and data.get("instance_id") == context["instance_id"]
                        and data.get("contract") == "mixar_ui_v1"):
                    ttl = data.get("valid_for_seconds")
                    if type(ttl) is int and 0 < ttl <= 60:
                        deadline = started+ttl
                        reason = "ready"
        else:
            reason = "signin_required"
    except requests.exceptions.RequestException as exc:
        log_network_failure(get_logger(__name__), classify_network_error(exc), context="mcp_ui_eligibility")
    except (ValueError, TypeError, KeyError):
        pass
    finally:
        with _lock:
            if generation == _generation:
                _deadline = deadline
                _reason = reason
            _refreshing = False
