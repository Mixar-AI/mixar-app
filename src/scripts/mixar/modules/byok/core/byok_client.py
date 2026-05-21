# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Async wrappers around the BYOK + models-catalog endpoints.

Each function spawns a daemon thread for the HTTP call and marshals the
result back onto Blender's main thread via `bpy.app.timers.register`.
Callers get a clean (success, data, error_message) tri-tuple and never
touch threads, HTTPClient, requests, or the APIResponse envelope.

The pattern mirrors `space_mixie_chat/ui/operators/auth_ops.py`.
"""

import threading
from typing import Any, Callable, Optional

from mixar.config.logging_config import get_logger

from ...common.api import APIResponse, get_agent_service

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# APIResponse → tri-tuple translation
# ---------------------------------------------------------------------------

_NETWORK_ERROR_MSG = "Could not reach Mixar. Check your connection and try again."
_VALIDATION_ERROR_MSG = "Invalid form data — please reach out to support."
_GENERIC_SERVER_ERROR_MSG = "Something went wrong on our end. Please try again."


def _translate(response: APIResponse) -> tuple[bool, Optional[Any], Optional[str]]:
    """Convert an APIResponse into a (success, data, error_message) tuple.

    The HTTPClient stores the full JSON body in `response.data`. The backend
    envelope shape is {"status", "message", "data"} — so on success we
    unwrap to the inner `data` dict, and on failure we pull the user-safe
    message from the envelope.

    For 400/502 the server's `message` is user-safe per the contract.
    422/500 get category defaults because those shapes aren't guaranteed
    (422 comes from FastAPI/Pydantic with a different structure).
    """
    envelope = response.data if isinstance(response.data, dict) else {}
    inner_data = envelope.get("data")
    server_message = envelope.get("message") or ""

    if response.success:
        return True, inner_data, None

    status = response.status_code
    if status == 422:
        return False, None, _VALIDATION_ERROR_MSG
    if status >= 500 and status != 502:
        return False, None, _GENERIC_SERVER_ERROR_MSG

    # 400, 502, 401 — envelope `message` is user-safe per the contract
    message = server_message or _GENERIC_SERVER_ERROR_MSG
    return False, None, message


# ---------------------------------------------------------------------------
# Main-thread callback marshaling
# ---------------------------------------------------------------------------

def _schedule_on_main(callback: Callable[..., None], *args) -> None:
    """Invoke `callback(*args)` on the Blender main thread via a zero-delay timer."""
    import bpy

    def _run():
        try:
            callback(*args)
        except Exception as e:
            logger.warning("BYOK main-thread callback failed: %s", e, exc_info=True)
        return None  # Don't repeat

    bpy.app.timers.register(_run, first_interval=0.0)


# ---------------------------------------------------------------------------
# BYOK credentials
# ---------------------------------------------------------------------------

def fetch_state(
    on_done: Callable[[bool, Optional[dict], Optional[str]], None],
) -> None:
    """GET /agent/credentials — current BYOK state for the logged-in user.

    On success the `data` arg of `on_done` is the response's inner `data`
    payload (dict with keys `byok_active`, `items`).
    """
    def _thread():
        try:
            response = get_agent_service().get_credentials()
            success, data, err = _translate(response)
        except Exception as e:
            logger.warning("BYOK fetch_state failed: %s", e)
            success, data, err = False, None, _NETWORK_ERROR_MSG
        _schedule_on_main(on_done, success, data, err)

    threading.Thread(
        target=_thread, daemon=True, name="MixarBYOKFetchState"
    ).start()


def save_credentials(
    provider: str,
    model: str,
    api_key: str,
    on_done: Callable[[bool, Optional[dict], Optional[str]], None],
) -> None:
    """PUT /agent/credentials/all — upsert BYOK config. ≤ 15 s."""
    def _thread():
        try:
            response = get_agent_service().save_credentials_all(
                provider=provider, model=model, api_key=api_key,
            )
            success, data, err = _translate(response)
        except Exception as e:
            logger.warning("BYOK save_credentials failed: %s", e)
            success, data, err = False, None, _NETWORK_ERROR_MSG
        _schedule_on_main(on_done, success, data, err)

    threading.Thread(
        target=_thread, daemon=True, name="MixarBYOKSave"
    ).start()


def delete_credentials(
    on_done: Callable[[bool, int, Optional[str]], None],
) -> None:
    """DELETE /agent/credentials/all — remove BYOK config. Always 200 on
    a reachable server; `removed_count` is the row count deleted.
    """
    def _thread():
        try:
            response = get_agent_service().delete_credentials_all()
            success, data, err = _translate(response)
            if success:
                removed = 0
                if isinstance(data, dict):
                    value = data.get("removed", 0)
                    if isinstance(value, int):
                        removed = value
                _schedule_on_main(on_done, True, removed, None)
            else:
                _schedule_on_main(on_done, False, 0, err)
        except Exception as e:
            logger.warning("BYOK delete_credentials failed: %s", e)
            _schedule_on_main(on_done, False, 0, _NETWORK_ERROR_MSG)

    threading.Thread(
        target=_thread, daemon=True, name="MixarBYOKDelete"
    ).start()


# ---------------------------------------------------------------------------
# Models catalog
# ---------------------------------------------------------------------------

def fetch_models_catalog(
    on_done: Callable[[bool, Optional[dict], Optional[str]], None],
) -> None:
    """GET /agent/models — provider + model catalog for dropdowns.

    Uses the existing `AgentService.list_models()` — same endpoint. On
    success the `data` arg of `on_done` is `{"providers": [...]}`.
    """
    def _thread():
        try:
            response = get_agent_service().list_models()
            success, data, err = _translate(response)
        except Exception as e:
            logger.warning("BYOK fetch_models_catalog failed: %s", e)
            success, data, err = False, None, _NETWORK_ERROR_MSG
        _schedule_on_main(on_done, success, data, err)

    threading.Thread(
        target=_thread, daemon=True, name="MixarBYOKModelsCatalog"
    ).start()
