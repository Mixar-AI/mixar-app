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

_VALIDATION_ERROR_MSG = n_("Invalid form data — please reach out to support.")
_GENERIC_SERVER_ERROR_MSG = n_("Something went wrong on our end. Please try again.")


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

# Saves and removals actually sent and not yet answered (main thread only:
# counted when the request starts, released just before its callback runs).
# The dialog reads it: closed with Esc mid-request and reopened, it must keep
# showing that request's progress instead of offering a second one.
_mutations_in_flight = 0
# Bumped by a logout reset: a request counted before it never releases into
# the next account's count.
_in_flight_generation = 0


def mutation_in_flight() -> bool:
    """A save or removal was sent and has not been answered yet."""
    return _mutations_in_flight > 0


def _track(on_done: Callable) -> Callable:
    """Count a request until its callback runs. The release happens before
    the caller's callback, so even a raising callback cannot leave it stuck;
    `_run_worker` guarantees the callback is delivered."""
    global _mutations_in_flight
    _mutations_in_flight += 1
    generation = _in_flight_generation
    released = [False]

    def _release():
        global _mutations_in_flight
        if not released[0]:
            released[0] = True
            if generation == _in_flight_generation:
                _mutations_in_flight = max(0, _mutations_in_flight - 1)

    def _done(*args):
        _release()
        on_done(*args)

    _done.release = _release
    return _done


def hold() -> Callable[[], None]:
    """Count a save that starts with local work before its HTTP call (the
    Local custom endpoint's ping); call the returned release once that work
    ends, then send the request (which counts itself)."""
    return _track(lambda *args: None).release


def reset_in_flight() -> None:
    """Logout: the next account must not wait on the previous one's request
    (its late callback is epoch-guarded and never drives the count negative)."""
    global _mutations_in_flight, _in_flight_generation
    _mutations_in_flight = 0
    _in_flight_generation += 1


def _run_worker(name: str, work: Callable[[], tuple], on_done: Callable,
                failure: tuple) -> None:
    """Run ``work`` off the main thread and ALWAYS deliver ``on_done(*result)``
    on the main thread — ``failure`` when anything at all goes wrong (even the
    error classification itself), on the calling (main) thread when no worker
    can be started. A request that never answers would otherwise leave
    the dialog busy and every key action refused for the session. (With no
    timer at all only the in-flight count is released: bpy is main-thread.)"""
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
    if len(failure) == 3 and isinstance(failure[1], int):
        return False, 0, err  # delete's (success, removed_count, error)
    return success, data, err


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
) -> None:
    """PUT /agent/byok — upsert BYOK config. ≤ 15 s.

    ``base_url`` / ``supports_vision`` are forwarded only when provided
    (the "local" provider's relay-target registration).
    """
    on_done = _track(on_done)

    def _work():
        response = get_agent_service().save_credentials_all(
            provider=provider, model=model, api_key=api_key,
            base_url=base_url, supports_vision=supports_vision,
        )
        return _translate(response)

    _run_worker("MixarBYOKSave", _work, on_done,
                (False, None, _GENERIC_SERVER_ERROR_MSG))


# An older server rejects the key-less switch as a schema error (422); say what
# to do instead of the generic form-data message.
_SWITCH_UNSUPPORTED_MSG = n_(
    "Couldn't switch the model here. Change it in AI Provider settings instead."
)


def switch_model(
    provider: str,
    model: str,
    on_done: Callable[[bool, Optional[dict], Optional[str]], None],
) -> None:
    """PUT /agent/byok with ``keep_stored_key`` — run the stored key on another
    model of the same provider. No key leaves the client; the server
    re-validates its stored key against ``model`` (≤ 15 s)."""
    def _work():
        try:
            response = get_agent_service().save_credentials_all(
                provider=provider, model=model, api_key=None, keep_stored_key=True,
            )
            success, data, err = _translate(response)
            status = getattr(response, "status_code", None)
        except Exception as e:  # noqa: BLE001
            logger.warning("BYOK switch_model failed: %s", e)
            success, data, err = _translate_exception(e)
            status = getattr(e, "status_code", None)
        if not success and status == 422:
            err = _SWITCH_UNSUPPORTED_MSG
        return success, data, err

    _run_worker("MixarBYOKSwitchModel", _work, on_done,
                (False, None, _GENERIC_SERVER_ERROR_MSG))


# An older server has no pause route (404/405) or rejects the body (422).
_STATE_UNSUPPORTED_MSG = n_(
    "Switching needs the latest Mixar server. Remove the key in AI Provider settings to go back to Mixie."
)


def set_key_enabled(
    enabled: bool,
    on_done: Callable[[bool, Optional[dict], Optional[str]], None],
) -> None:
    """PUT /agent/byok/state — the island toggle: pause the stored key so Mixie
    answers (False), or resume it (True). The key is never sent or deleted;
    the echo is the credential list with the resulting ``byok_active``."""
    def _work():
        try:
            response = get_agent_service().set_byok_state(enabled)
            success, data, err = _translate(response)
            status = getattr(response, "status_code", None)
        except Exception as e:  # noqa: BLE001
            logger.warning("BYOK set_key_enabled failed: %s", e)
            success, data, err = _translate_exception(e)
            status = getattr(e, "status_code", None)
        if not success and status in (404, 405, 422):
            err = _STATE_UNSUPPORTED_MSG
        return success, data, err

    _run_worker("MixarBYOKSetEnabled", _work, on_done,
                (False, None, _GENERIC_SERVER_ERROR_MSG))


def delete_credentials(
    on_done: Callable[[bool, int, Optional[str]], None],
) -> None:
    """DELETE /agent/credentials/all — remove BYOK config. Always 200 on
    a reachable server; `removed_count` is the row count deleted.
    """
    on_done = _track(on_done)

    def _work():
        response = get_agent_service().delete_credentials_all()
        success, data, err = _translate(response)
        if not success:
            return False, 0, err
        removed = data.get("removed", 0) if isinstance(data, dict) else 0
        return True, removed if isinstance(removed, int) else 0, None

    _run_worker("MixarBYOKDelete", _work, on_done,
                (False, 0, _GENERIC_SERVER_ERROR_MSG))
