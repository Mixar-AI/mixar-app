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


def _translate_exception(exc: Exception) -> tuple[bool, Optional[Any], Optional[str]]:
    """Convert an exception raised by the HTTP layer into a (success, data, error)
    tuple, applying the same status policy as `_translate`.

    The HTTPClient raises (raise_for_status defaults to True), so non-2xx
    responses arrive here as `HTTPClientError` subclasses rather than as an
    APIResponse. Each carries `.status_code` and `.message`; `_map_exception`
    has already dug the user-safe text out of the backend's
    {"detail": {"message": ...}} envelope. We must surface that message instead
    of collapsing everything to the generic network error.

    Genuine connection/timeout failures — and retry-exhausted 5xx, which reach
    us as a bare HTTPClientError with `status_code=None` — fall back to the
    network message.
    """
    status = getattr(exc, "status_code", None)
    message = getattr(exc, "message", None)

    if status is None:
        # Connection/timeout/retry-exhaustion — not a clean HTTP response.
        return False, None, _NETWORK_ERROR_MSG
    if status == 422:
        return False, None, _VALIDATION_ERROR_MSG
    if status >= 500 and status != 502:
        return False, None, _GENERIC_SERVER_ERROR_MSG
    # 400, 401, 403, 404, 429, 502 — server `message` is user-safe per the
    # contract (e.g. "Model not available: ...", "API key rejected: ...").
    return False, None, message or _GENERIC_SERVER_ERROR_MSG


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
            success, data, err = _translate_exception(e)
        _schedule_on_main(on_done, success, data, err)

    threading.Thread(
        target=_thread, daemon=True, name="MixarBYOKFetchState"
    ).start()


def save_credentials(
    provider: str,
    model: str,
    on_done: Callable[[bool, Optional[dict], Optional[str]], None],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> None:
    """PUT /agent/byok — upsert BYOK config. ≤ 15 s.

    Cloud providers pass ``api_key``; the local provider passes ``base_url``
    (its endpoint) and no key.
    """
    def _thread():
        try:
            response = get_agent_service().save_credentials_all(
                provider=provider, model=model, api_key=api_key, base_url=base_url,
            )
            success, data, err = _translate(response)
        except Exception as e:
            logger.warning("BYOK save_credentials failed: %s", e)
            success, data, err = _translate_exception(e)
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
            _, _, err = _translate_exception(e)
            _schedule_on_main(on_done, False, 0, err)

    threading.Thread(
        target=_thread, daemon=True, name="MixarBYOKDelete"
    ).start()


# ---------------------------------------------------------------------------
# Local endpoint reachability (client-side — hits the user's own localhost)
# ---------------------------------------------------------------------------

def ping_local_endpoint(
    base_url: str,
    on_done: Callable[[bool, Optional[str]], None],
) -> None:
    """Check a local model server is reachable, off the main thread.

    The backend cannot validate a localhost URL (it can't see the user's
    machine), so this runs here where localhost resolves correctly. Calls
    ``on_done(reachable, error_message)`` back on the main thread.
    """
    def _thread():
        try:
            from .local_llm_relay import ping_endpoint
            reachable, err = ping_endpoint(base_url)
        except Exception as e:  # noqa: BLE001
            logger.warning("BYOK ping_local_endpoint failed: %s", e)
            reachable, err = False, "Could not check the local server."
        _schedule_on_main(on_done, reachable, err)

    threading.Thread(
        target=_thread, daemon=True, name="MixarBYOKLocalPing"
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
            success, data, err = _translate_exception(e)
        _schedule_on_main(on_done, success, data, err)

    threading.Thread(
        target=_thread, daemon=True, name="MixarBYOKModelsCatalog"
    ).start()
