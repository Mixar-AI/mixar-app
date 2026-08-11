# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded, fail-open desktop event queue.

Callers snapshot primitive values on Blender's main thread. The worker owns all
network I/O and never imports or touches bpy.
"""

from __future__ import annotations

import functools
import platform
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from mixar.config.config import get_config, get_environment, get_ui_mode
from mixar.config.logging_config import get_logger

from .constants import (
    BATCH_SIZE,
    EVENT_OPERATOR,
    FLUSH_INTERVAL_SECONDS,
    IGNORED_OPERATORS,
    MAX_PROPERTIES,
    MAX_QUEUE_SIZE,
    SHUTDOWN_TIMEOUT_SECONDS,
)
from .preferences import is_enabled

logger = get_logger(__name__)

_events: queue.Queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
_wake = threading.Event()
_stop = threading.Event()
_worker: threading.Thread | None = None
_lock = threading.Lock()
_events_dropped = 0
_cached_context_properties: dict[str, str | None] = {}
_suppressed = False
_shutdown = False

_AUTH_CACHE_TTL_SECONDS = 30.0
_auth_cache: tuple[float, bool] | None = None


def suppress() -> None:
    """Silence telemetry for this process.

    Used for headless/background runs. Mixar spawns ``--background`` children
    itself (the create_model sandbox processes), and those authenticate from
    the same keyring as the user's real session — so without this every one
    of them reports a zero-duration session and corrupts session metrics.
    """
    global _suppressed
    _suppressed = True


def _primitive_properties(
    properties: dict[str, Any],
) -> dict[str, str | int | float | bool | None]:
    cleaned = {}
    for key, value in list(properties.items())[:MAX_PROPERTIES]:
        if not isinstance(key, str) or not key or len(key) > 64:
            continue
        if value is None or isinstance(value, (bool, int, float)):
            cleaned[key] = value
        elif isinstance(value, str):
            cleaned[key] = value[:256]
    return cleaned


def _common_properties(context=None) -> dict:
    config = get_config()
    props = {
        "app_version": config.get("app_info", {}).get("version", "unknown"),
        "environment": get_environment(),
        "ui_mode": get_ui_mode(),
        "platform": platform.system().lower(),
    }
    if context is not None:
        wm = getattr(context, "window_manager", None)
        scene = getattr(context, "scene", None)
        props["instance_id"] = getattr(wm, "mixie_instance_id", "") or None
        props["session_id"] = getattr(scene, "mixie_session_id", "") or None
        # Keep the last known-good ids for teardown, where bpy.context is
        # unreliable; a context that momentarily lacks them must not erase.
        _cached_context_properties.update({
            key: props[key]
            for key in ("instance_id", "session_id")
            if props[key] is not None
        })
    return props


def capture(event: str, properties: dict | None = None, *, context=None) -> None:
    """Queue one content-free event without ever breaking its caller."""
    try:
        # Authenticated-only by design: never retain pre-login behavior and
        # never attribute an anonymous event to whichever account signs in
        # later. Gate first: this runs on every operator execution, so an
        # opted-out user must not pay for config lookups — or have their ids
        # cached — on that path.
        if _suppressed or _shutdown or not is_enabled() or not event:
            return
        if not _has_auth_token():
            return
        common = _common_properties(context)
        payload = {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": uuid.uuid4().hex,
            "properties": _primitive_properties({
                **common,
                **(properties or {}),
            }),
        }
        global _events_dropped
        try:
            _events.put_nowait(payload)
        except queue.Full:
            _events_dropped += 1
            logger.debug("Telemetry queue full; dropping event %s", event)
            return
        _ensure_worker()
        if _events.qsize() >= BATCH_SIZE:
            _wake.set()
    except Exception as exc:  # noqa: BLE001 - analytics is deliberately fail-open
        logger.debug("Telemetry capture failed for %s: %s", event, exc)


def events_dropped() -> int:
    return _events_dropped


def cached_context_properties() -> dict[str, str | None]:
    return dict(_cached_context_properties)


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _stop.clear()
        _worker = threading.Thread(
            target=_worker_loop, name="MixarTelemetry", daemon=True
        )
        _worker.start()


def _take_batch() -> list[dict]:
    batch = []
    while len(batch) < BATCH_SIZE:
        try:
            batch.append(_events.get_nowait())
        except queue.Empty:
            break
    return batch


def _send(batch: list[dict]) -> None:
    if not batch:
        return
    try:
        _post_batch(batch)
    except Exception as exc:  # noqa: BLE001 - analytics is deliberately fail-open
        logger.debug("Telemetry delivery failed: %s", exc)


def _has_auth_token() -> bool:
    """Lazy import keeps analytics safe during early bootstrap and unit tests.

    The result is cached briefly: the token lives in the OS keyring (macOS
    Keychain / Windows Credential Manager) and this runs on the main thread
    for every captured event, so an uncached lookup would mean a synchronous
    credential-store round trip per operator click.
    """
    global _auth_cache
    now = time.monotonic()
    if _auth_cache is not None and now - _auth_cache[0] < _AUTH_CACHE_TTL_SECONDS:
        return _auth_cache[1]
    try:
        from mixar.modules.auth.core.auth import get_access_token
        result = bool(get_access_token())
    except Exception:
        return False
    _auth_cache = (now, result)
    return result


def _post_batch(batch: list[dict]) -> None:
    from mixar.modules.common.api.client import get_http_client

    get_http_client().post(
        "api/v1/telemetry/events",
        json={"events": batch},
        timeout=5.0,
    )


def _worker_loop() -> None:
    deadline = time.monotonic() + FLUSH_INTERVAL_SECONDS
    while not _stop.is_set():
        timeout = max(0.0, deadline - time.monotonic())
        _wake.wait(timeout)
        _wake.clear()
        if _events.qsize() >= BATCH_SIZE or time.monotonic() >= deadline:
            _send(_take_batch())
            deadline = time.monotonic() + FLUSH_INTERVAL_SECONDS
    while not _events.empty():
        _send(_take_batch())


def shutdown() -> None:
    """Request a bounded final flush during addon/application teardown.

    Also bars further captures: a late capture would otherwise restart the
    worker thread, and ``Thread.start()`` raises during interpreter teardown.
    """
    global _worker, _shutdown
    _shutdown = True
    worker = _worker
    if worker is None:
        return
    _stop.set()
    _wake.set()
    worker.join(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    _worker = None


def _successful(result) -> bool:
    # RUNNING_MODAL counts: for modal operators (wrapped on invoke) it means
    # the operator started; reporting those as failures poisons success rates.
    return isinstance(result, set) and bool(result & {"FINISHED", "RUNNING_MODAL"})


def _operator_wrapper(original, op_id: str, *, with_event: bool):
    """Build a wrapper with the exact RNA method signature.

    register_class validates each overridden method's code object by its
    positional-argument count. A ``*args`` shim therefore registers for
    ``execute`` (2 args) but rejects every invoke-only operator (``invoke``
    expects 3): "expected Operator ... function to have 3 args, found 2" —
    which silently disabled modal operators like Director's Navigate.
    """
    if with_event:

        @functools.wraps(original)
        def wrapped(self, context, event):
            result = original(self, context, event)
            capture(EVENT_OPERATOR, {
                "operator": op_id,
                "success": _successful(result),
            }, context=context)
            return result

    else:

        @functools.wraps(original)
        def wrapped(self, context):
            result = original(self, context)
            capture(EVENT_OPERATOR, {
                "operator": op_id,
                "success": _successful(result),
            }, context=context)
            return result

    return wrapped


def instrument_operator_classes(classes) -> None:
    """Wrap Mixar-owned operators once, preferring execute over invoke.

    Only operator identity and success are captured. RNA properties/arguments
    are intentionally excluded because they can contain prompts or file paths.
    """
    for cls in classes or ():
        op_id = getattr(cls, "bl_idname", "")
        if (
            not op_id
            or op_id in IGNORED_OPERATORS
            or getattr(cls, "__mixar_analytics_wrapped__", False)
        ):
            continue
        method_name = "execute" if callable(getattr(cls, "execute", None)) else "invoke"
        original = getattr(cls, method_name, None)
        if not callable(original):
            continue
        wrapped = _operator_wrapper(
            original, op_id, with_event=method_name == "invoke"
        )
        setattr(cls, method_name, wrapped)
        cls.__mixar_analytics_wrapped__ = True
