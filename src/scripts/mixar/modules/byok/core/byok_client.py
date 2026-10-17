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
from threading import current_thread, main_thread
from typing import Any, Callable, Optional

from mixar.config.config import get_server_url
from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ...common.api import APIResponse, get_agent_service
from ...common.network import classify_network_error, log_network_failure
from ..constants import BYOK_TURN_ACCOUNT_FIELD, BYOK_TURN_KEY_FIELD, LOCAL_PROVIDER_ID

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
# Requests in flight (main thread) and the always-answering worker
# ---------------------------------------------------------------------------

# Saves, removals and in-place re-saves actually sent and not yet answered
# (main thread only: counted when the request starts, released just before
# its callback runs). The dialog reads it: closed with Esc mid-request and
# reopened, it must keep showing that request's progress instead of offering
# a second one; the island's toggle and model switch wait for it too.
_mutations_in_flight = 0
# Bumped by a logout reset: a request counted before it never releases into
# the next account's count.
_in_flight_generation = 0

_NO_STORED_KEY_MSG = n_(
    "No saved key on this computer. Enter it in AI Provider Settings."
)
_SIGNED_OUT_MSG = n_("Signed out before the request finished.")


def _account_epoch() -> int:
    """The credential lifecycle epoch (bumped by logout): captured at submit,
    compared on the worker before the network call, so a logout + sign-in
    as another account inside that window (a Codex refresh can take seconds)
    never sends the first account's key with the second account's token."""
    from . import credential_state

    return credential_state.current_epoch()


def mutation_in_flight() -> bool:
    """A save, removal or in-place re-save was sent and has not been answered yet."""
    return _mutations_in_flight > 0


def _mirror_busy() -> None:
    """Re-write the island picker's mirror: its BUSY state follows the count
    (the card words its gate from it). Main thread only — the count is also
    released off-thread at interpreter shutdown, where bpy is off limits."""
    if current_thread() is not main_thread():
        return
    try:
        from . import picker_mirror

        picker_mirror.apply_to_wm()
    except Exception as e:  # noqa: BLE001 — a mirror write never blocks a request
        logger.debug("BYOK picker mirror not refreshed: %s", e)


def _track(on_done: Callable) -> Callable:
    """Count a request until its callback runs (released BEFORE the caller's
    callback, so a raising callback cannot leave it stuck)."""
    global _mutations_in_flight
    _mutations_in_flight += 1
    generation = _in_flight_generation
    released = [False]
    _mirror_busy()

    def _release():
        global _mutations_in_flight
        if not released[0]:
            released[0] = True
            if generation == _in_flight_generation:
                _mutations_in_flight = max(0, _mutations_in_flight - 1)
                _mirror_busy()

    def _done(*args):
        _release()
        on_done(*args)

    _done.release = _release
    return _done


def hold() -> Callable[[], None]:
    """Count a save that starts with local work before its HTTP call (the
    Local ping); release once that work ends, then send (which counts itself)."""
    return _track(lambda *args: None).release


def reset_in_flight() -> None:
    """Logout: the next account must not wait on the previous one's request."""
    global _mutations_in_flight, _in_flight_generation
    _mutations_in_flight = 0
    _in_flight_generation += 1
    _mirror_busy()


def _run_worker(name: str, work: Callable[[], tuple], on_done: Callable,
                failure: tuple) -> None:
    """Run ``work`` off the main thread and ALWAYS deliver ``on_done(*result)``
    on the main thread — ``failure`` when anything goes wrong (even the error
    classification), on the calling thread when no worker can start; with no
    timer at all only the in-flight count is released (bpy is main-thread)."""
    def _deliver(result):
        try:
            _schedule_on_main(on_done, *result)
        except Exception as e:  # noqa: BLE001
            # No timer (interpreter shutdown): never touch bpy from this
            # thread; just release the in-flight count.
            logger.warning("BYOK %s: main-thread delivery failed: %s", name, e)
            getattr(on_done, "release", lambda: None)()

    def _thread():
        result = failure
        try:
            result = work()
        except Exception as e:  # noqa: BLE001
            logger.warning("BYOK %s failed: %s", name, e)
            try:
                result = _shape_exception(e, failure)
            except Exception as inner:  # noqa: BLE001
                logger.warning("BYOK %s: error classification failed: %s", name, inner)
        finally:
            _deliver(result)

    try:
        threading.Thread(target=_thread, daemon=True, name=name).start()
    except Exception as e:  # noqa: BLE001
        logger.warning("BYOK %s: worker not started: %s", name, e)
        on_done(*failure)


def _shape_exception(exc: Exception, failure: tuple) -> tuple:
    """`_translate_exception`'s tri-tuple, in the arity ``failure`` uses."""
    if len(failure) != 3:
        return failure
    success, data, err = _translate_exception(exc)
    return (False, 0, err) if isinstance(failure[1], int) else (success, data, err)


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
    def _work():
        return _translate(get_agent_service().get_credentials())

    _run_worker("MixarBYOKFetchState", _work, on_done,
                (False, None, _GENERIC_SERVER_ERROR_MSG))


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

    ``base_url`` / ``supports_vision`` only when provided (Local);
    ``account_id`` only for Codex; ``codex_auth_path`` is NEVER sent — it is
    this device's reference to the CLI's sign-in file. The key goes out
    SEALED (`transport_seal`; a stale-transport-key 409 repeats the PUT once
    with a fresh envelope). On 200 the record — with ``model``, which a later
    resume re-sends — is written to this device's store on the worker thread,
    before the callback; a store write that fails is an ERROR carrying the
    server's state (the account is active, this device cannot sign a turn).
    A local ``model`` that is a path is sent as its basename. Counted in
    flight until the callback (`mutation_in_flight`).
    """
    if provider == LOCAL_PROVIDER_ID:
        from mixar.modules.local_models.core.model_name import safe_model_name
        model = safe_model_name(model)

    on_done = _track(on_done)

    def _work():
        from . import key_store

        user_id = key_store.current_user_id()  # before the call: never the next account's
        success, data, err = _put_sealed(provider, model, api_key, base_url,
                                         supports_vision, account_id)
        if success and not _store_local_key(provider, api_key, codex_auth_path, model, user_id):
            success, err = False, _LOCAL_STORE_FAILED_MSG
        return success, data, err

    _run_worker("MixarBYOKSave", _work, on_done,
                (False, None, _GENERIC_SERVER_ERROR_MSG))


def resave_stored_key(
    model: Optional[str],
    on_done: Callable[[bool, Optional[dict], Optional[str]], None],
) -> None:
    """PUT /agent/byok with the key THIS DEVICE already holds — nothing is
    typed. Island callers: the key chip's model switch (``model`` is the new
    model, same provider) and the model card resuming a paused key (``model``
    None: the record's own). The server re-validates like a fresh save.
    Worker thread: load the record, read / renew a Codex sign-in exactly as
    before a turn (`turn_credentials.resolve`, renewals written back to the
    file), seal through `_put_sealed`, update the record's ``model`` on 200.
    Refused before anything is sent when this device holds no key, the
    record names no model or the provider is Local (its endpoint is not in
    the record). Counted in flight like a save.
    """
    on_done = _track(on_done)
    epoch = _account_epoch()

    def _work():
        from . import codex_auth, key_store, turn_credentials

        user_id = key_store.current_user_id()
        record = key_store.load(user_id)
        if record is None or (record.get("provider") or "") in ("", LOCAL_PROVIDER_ID):
            return False, None, _NO_STORED_KEY_MSG
        provider = record["provider"]
        target = (model or record.get("model") or "").strip()
        if not target:
            return False, None, _NO_STORED_KEY_MSG
        live, problem = key_store.materialize(record)
        if problem is not None:
            return False, None, problem
        resolution = turn_credentials.resolve(live, refresher=codex_auth.refresh_access_token)
        if resolution.blocked:
            return False, None, resolution.error
        if resolution.record_changes and not key_store.persist_changes(
                live, resolution.record_changes, user_id):
            # The grant rotated the refresh token and the file could not take
            # it: the next turn will refresh with a stale token and read as
            # revoked. Say so in the log; the turn path has the same gap.
            logger.warning("BYOK Codex renewal could not be written back to the sign-in file")
        api_key = resolution.fields.get(BYOK_TURN_KEY_FIELD)
        if not api_key:
            return False, None, _NO_STORED_KEY_MSG
        account_id = resolution.fields.get(BYOK_TURN_ACCOUNT_FIELD)
        if epoch != _account_epoch():
            return False, None, _SIGNED_OUT_MSG
        success, data, err = _put_sealed(provider, target, api_key, None, None, account_id)
        if success and not key_store.update({"model": target}, user_id):
            # The server runs the new model; only a later resume would re-send
            # the old one. Not an error the user can act on.
            logger.warning("BYOK model switched, but this device's record kept the old model")
        return success, data, err

    _run_worker("MixarBYOKResave", _work, on_done,
                (False, None, _GENERIC_SERVER_ERROR_MSG))


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
    *,
    forget_local: bool = True,
) -> None:
    """DELETE /agent/credentials/all — remove BYOK config (`removed_count`
    rows). ``forget_local`` False keeps this device's key record: the
    island's Mixie pick PAUSES the key and a key-tab pick re-sends it later
    (`resave_stored_key`); "Remove key" and the chat card delete both.
    Counted in flight like a save.
    """
    on_done = _track(on_done)
    epoch = _account_epoch()

    def _work():
        from . import key_store

        if epoch != _account_epoch():
            return False, 0, _SIGNED_OUT_MSG
        user_id = key_store.current_user_id()  # before the call: never the next account's
        response = get_agent_service().delete_credentials_all()
        success, data, err = _translate(response)
        if not success:
            return False, 0, err
        removed = data.get("removed", 0) if isinstance(data, dict) else 0
        if forget_local:
            _forget_local_key(user_id)
        return True, removed if isinstance(removed, int) else 0, None

    _run_worker("MixarBYOKDelete", _work, on_done,
                (False, 0, _GENERIC_SERVER_ERROR_MSG))


def forget_stored_key(on_done: Callable[[bool], None]) -> None:
    """Delete this device's key record only (a paused key the user no longer
    wants kept); nothing is sent. ``on_done(deleted)`` on the main thread."""
    on_done = _track(on_done)
    epoch = _account_epoch()

    def _work():
        from . import key_store

        if epoch != _account_epoch():
            return (False,)  # another account's record by now
        return (bool(key_store.delete()),)

    _run_worker("MixarBYOKForget", _work, on_done, (False,))


# ---------------------------------------------------------------------------
# This device's copy of the key (worker thread; the store blocks)
# ---------------------------------------------------------------------------

def _store_local_key(provider, api_key, codex_auth_path, model, user_id=None) -> bool:
    """True when the record is in this device's store (Codex: the file
    reference only — never the tokens), under ``user_id`` (the account the
    request was made as; None resolves the current token)."""
    try:
        from . import key_store

        record = key_store.make_record(provider, api_key, auth_path=codex_auth_path, model=model)
        if key_store.save(record, user_id):
            return True
        logger.warning("BYOK key was validated but could not be stored on this device")
    except Exception as e:  # noqa: BLE001 — the server state is already saved
        logger.warning("BYOK local key store write failed: %s", type(e).__name__)
    return False


def _forget_local_key(user_id=None) -> None:
    try:
        from . import key_store

        key_store.delete(user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("BYOK local key store delete failed: %s", type(e).__name__)
