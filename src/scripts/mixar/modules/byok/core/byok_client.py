# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Async wrappers around the BYOK credential endpoints.

Each function spawns a daemon thread for the HTTP call and marshals the
result back onto Blender's main thread via `bpy.app.timers.register`.
Callers get a clean (success, data, error_message) tri-tuple and never
touch threads, HTTPClient, requests, or the APIResponse envelope.

The provider/model CATALOG is not here — it has a different lifecycle (disk
cache + ETag revalidation, no per-user secret) and lives in
`byok/core/models_cache.py`. This module owns only the per-user credential
state and the mutations.

The tri-tuple signatures are a fixed contract: ten call sites and four test
modules depend on them. Do not widen them.
"""

import threading
from typing import Any, Callable, Optional

from mixar.config.config import get_server_url
from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ...common.api import APIResponse, get_agent_service
from ...common.network import classify_network_error, log_network_failure

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# APIResponse → tri-tuple translation
# ---------------------------------------------------------------------------

_VALIDATION_ERROR_MSG = n_("Something is wrong with this form. Please contact support.")
_GENERIC_SERVER_ERROR_MSG = n_("Something went wrong on our end. Please try again.")
_LOCAL_STORE_FAILED_MSG = n_(
    "Your key works, but Mixar could not save it on this computer. Enter it "
    "again to retry."
)


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
        # Connection/timeout/retry-exhaustion — not a clean HTTP response, so
        # route it through the shared classifier instead of a hand-rolled
        # string. `failure.user_text` carries a NET-* support code the user can
        # quote and IT can act on; a flat "could not reach Mixar" tells a
        # customer behind a TLS-inspecting proxy nothing at all, and is banned
        # by the network contract (pinned by tests/network/).
        failure = classify_network_error(exc, url=get_server_url())
        log_network_failure(logger, failure, "BYOK request")
        return False, None, failure.user_text
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


# Shared with `preference_client`. The hosted model-preference endpoints sit on
# the same router, return the same {status, message, data} envelope and raise the
# same HTTPClientError subclasses, so they get the same status policy and the
# same NET-* classification rather than a second copy of it. Exported as public
# names so that reuse is a stated contract, not a reach into a private.
translate_response = _translate
translate_exception = _translate_exception
schedule_on_main = _schedule_on_main


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
    api_key: Optional[str],
    on_done: Callable[[bool, Optional[dict], Optional[str]], None],
    base_url: Optional[str] = None,
    supports_vision: Optional[bool] = None,
    account_id: Optional[str] = None,
    codex_auth_path: Optional[str] = None,
) -> None:
    """PUT /agent/byok — validate + register BYOK config. ≤ 15 s.

    ``base_url`` / ``supports_vision`` are forwarded only when provided
    (the "local" provider's relay-target registration); ``account_id`` only
    for Codex. ``codex_auth_path`` (Codex) is NEVER sent — it is the
    reference this device keeps to the Codex CLI's sign-in file; the tokens
    themselves stay in that file.

    On 200 the key material is written to this device's credential store
    (`key_store`) — still on the worker thread, before the callback — so the
    next turn can carry it. The server keeps metadata only. A store write
    that fails is reported as an ERROR (with the server's state attached, so
    the card still shows the truth): the account is BYOK-active and this
    device cannot sign a turn, which a "Saved" recap would hide until the
    next message's 409.

    The key is SEALED to the backend's transport key before the PUT
    (`transport_seal`, on this worker thread); this device's store keeps the
    plaintext — sealing is transport only. A 409 ``byok_transport_key_stale``
    (the server rotated its key inside our cache window) drops the cached
    key and repeats the PUT once with a fresh envelope.
    """
    def _thread():
        success, data, err = _put_sealed(provider, model, api_key, base_url,
                                         supports_vision, account_id)
        if success and not _store_local_key(provider, api_key, codex_auth_path):
            success, err = False, _LOCAL_STORE_FAILED_MSG
        _schedule_on_main(on_done, success, data, err)

    threading.Thread(
        target=_thread, daemon=True, name="MixarBYOKSave"
    ).start()


def _put_sealed(provider, model, api_key, base_url, supports_vision, account_id,
                *, retried: bool = False) -> tuple[bool, Optional[Any], Optional[str]]:
    """The PUT with ``api_key`` sealed; a key that cannot be sealed is an
    ERROR (the user-safe `SealError` message) and nothing is sent."""
    from . import transport_seal

    envelope = None
    if api_key is not None:
        try:
            envelope = transport_seal.seal(api_key)
        except transport_seal.SealError as exc:
            return False, None, exc.message
    try:
        response = get_agent_service().save_credentials_all(
            provider=provider, model=model, api_key=envelope,
            base_url=base_url, supports_vision=supports_vision,
            account_id=account_id,
        )
        return _translate(response)
    except Exception as e:
        if envelope is not None and not retried and is_stale_transport_key(e):
            transport_seal.invalidate()
            return _put_sealed(provider, model, api_key, base_url, supports_vision,
                               account_id, retried=True)
        logger.warning("BYOK save_credentials failed: %s", e)
        return _translate_exception(e)


def error_code(exc: Exception) -> str:
    """The backend's ``code`` on an HTTP error (``{"detail": {"code": …}}``
    or a flat envelope), or ''."""
    body = getattr(exc, "response_data", None)
    if not isinstance(body, dict):
        return ""
    detail = body.get("detail")
    source = detail if isinstance(detail, dict) else body
    code = source.get("code")
    return code if isinstance(code, str) else ""


def is_stale_transport_key(exc: Exception) -> bool:
    from ..constants import BYOK_TRANSPORT_KEY_STALE_CODE

    return (getattr(exc, "status_code", None) == 409
            and error_code(exc) == BYOK_TRANSPORT_KEY_STALE_CODE)


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
                _forget_local_key()
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
# This device's copy of the key (worker thread; the store blocks)
# ---------------------------------------------------------------------------

def _store_local_key(provider, api_key, codex_auth_path) -> bool:
    """True when the record is in this device's store (Codex: the file
    reference only — never the tokens)."""
    try:
        from . import key_store

        record = key_store.make_record(provider, api_key, auth_path=codex_auth_path)
        if key_store.save(record):
            return True
        logger.warning("BYOK key was validated but could not be stored on this device")
    except Exception as e:  # noqa: BLE001 — the server state is already saved
        logger.warning("BYOK local key store write failed: %s", type(e).__name__)
    return False


def _forget_local_key() -> None:
    try:
        from . import key_store

        key_store.delete()
    except Exception as e:  # noqa: BLE001
        logger.warning("BYOK local key store delete failed: %s", type(e).__name__)
