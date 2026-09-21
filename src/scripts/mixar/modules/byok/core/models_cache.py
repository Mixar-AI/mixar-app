# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stale-while-revalidate cache for the agent provider/model catalog.

Modelled on `bootstrap/generation_catalog_cache.py`. The lifecycle shim that
calls `load_from_disk()` and arms the timers is `bootstrap/byok_module.py`;
everything here is transport and state, importable without `mixar.bootstrap`.

Why a disk cache at all: the BYOK dropdowns used to be empty until a network
round trip landed, and under the WebSocket transport that round trip could not
even be attempted until the agent socket had handshaken. Loading the last known
catalog from disk during bootstrap phase 3 — before UI auto-discovery imports
the dialog's panels — means the dropdowns are populated the first time they
draw, offline included.

Revalidation is cheap BECAUSE of the ETag: a 304 does not call
`model_suggestions.populate()` at all, so the enum lists are rebuilt only when
the catalog genuinely changed. That is strictly less churn than the old
fetch-on-every-login, which mattered because Blender's EnumProperty stores the
raw char* of the strings those lists hold.
"""

import threading
from typing import Any, Dict, Optional

from mixar.config.logging_config import get_logger

from ...common.api import get_agent_service
from . import models_storage, model_suggestions

logger = get_logger(__name__)

# Guards the in-memory state. Never held across network or disk I/O.
_lock = threading.Lock()
# Guards disk I/O separately, so a UI-driven clear() cannot block behind fsync
# and so an invalidated worker can never recreate a file clear() just deleted.
_persistence_lock = threading.Lock()

_etag: Optional[str] = None
_is_loading: bool = False
_shutdown_requested: bool = False
# Monotonic token snapshotted at fetch start and re-checked before the swap. A
# logout mid-flight bumps it, which turns a late 200 into a no-op instead of
# repopulating the previous account's catalog.
_lifecycle_epoch: int = 0


def reset_lifecycle() -> None:
    """Start a new lifecycle (called from register()).

    Drops the ETag deliberately. It is only valid alongside the catalog it
    describes, and register() has not loaded that yet — `load_from_disk()`
    re-establishes the pair a moment later. Keeping a stale tag across a script
    reload would answer 304 against an empty suggestion cache and leave the
    dropdowns blank with nothing to retry.
    """
    global _lifecycle_epoch, _shutdown_requested, _is_loading, _etag
    with _lock:
        _lifecycle_epoch += 1
        _shutdown_requested = False
        _is_loading = False
        _etag = None


def mark_shutdown() -> None:
    """Stop scheduling new main-thread work. Safe at interpreter teardown.

    Touches no bpy data: `BPY_python_end` runs after `BKE_blender_free()`, so an
    RNA write from an atexit hook is a use-after-free.
    """
    global _shutdown_requested
    with _lock:
        _shutdown_requested = True


def is_loaded() -> bool:
    """True once a catalog (from disk or the network) has been applied."""
    return model_suggestions.is_loaded()


def load_from_disk() -> bool:
    """Populate the suggestion cache from the persisted payload. Main thread.

    Returns True when something was applied. `populate_from_payload` touches no
    bpy, so this is safe during bootstrap phase 3 — before `byok_props`
    registers its EnumProperties in phase 4.
    """
    global _etag
    stored = models_storage.load()
    if not stored:
        return False
    data, etag = stored
    with _lock:
        _etag = etag
    model_suggestions.populate_from_payload(data)
    logger.debug("Agent models catalog loaded from disk (etag=%s)", etag)
    return True


def refresh() -> None:
    """Revalidate the catalog on a daemon thread. No-op while one is in flight."""
    global _is_loading
    with _lock:
        if _shutdown_requested or _is_loading:
            return
        _is_loading = True
        epoch = _lifecycle_epoch
        etag = _etag

    threading.Thread(
        target=_fetch_worker, args=(epoch, etag),
        daemon=True, name="MixarAgentModelsCatalog",
    ).start()


def clear() -> None:
    """Drop the catalog everywhere — memory, suggestions, disk. Called on logout.

    Bumps the epoch first so a worker already in flight cannot repopulate after
    this returns, then deletes under `_persistence_lock` so it cannot recreate
    the file either.
    """
    global _etag, _lifecycle_epoch, _is_loading
    with _lock:
        _lifecycle_epoch += 1
        _etag = None
        _is_loading = False
    model_suggestions.clear()
    with _persistence_lock:
        models_storage.delete()


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _fetch_worker(epoch: int, etag: Optional[str]) -> None:
    """Daemon thread: revalidate, then marshal the apply onto the main thread."""
    global _etag, _is_loading
    try:
        # The bootstrap timer fires ~2s in, which can beat the login hook. Skip
        # rather than spend a guaranteed 401 on every launch — the auth hook
        # re-fires this the moment the token is validated. Checked on the worker
        # (keyring reads can block) like generation_catalog_cache does.
        from mixar.modules.auth.core.auth import get_access_token

        if not get_access_token():
            logger.debug("Skipping agent models catalog fetch: not authenticated")
            return

        response = get_agent_service().list_models(etag=etag)

        # 304 BEFORE success: APIResponse.success is `response.ok`, which is
        # True at 304, and the body is empty. Checking success first would swap
        # a live catalog for nothing.
        if response.status_code == 304:
            logger.debug("Agent models catalog unchanged (304)")
            return

        if not response.success:
            logger.debug("Agent models catalog fetch failed: %s", response.status_code)
            return

        envelope = response.data if isinstance(response.data, dict) else {}
        data = envelope.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("providers"), list):
            logger.debug("Agent models catalog payload malformed; keeping cache")
            return

        new_etag = response.headers.get("ETag") or response.headers.get("etag")

        with _lock:
            if epoch != _lifecycle_epoch or _shutdown_requested:
                logger.debug("Agent models catalog response dropped (stale epoch)")
                return
            _etag = new_etag

        # An authoritative empty list is the backend's kill switch and must
        # replace the cache, not be treated as malformed (fail closed).
        _schedule_populate(epoch, data)

        with _persistence_lock:
            # Second epoch check, under the persistence lock: clear() bumps
            # the epoch under `_lock` and only THEN deletes under
            # `_persistence_lock`, so a logout between the check above and
            # this save would otherwise recreate the file it just deleted.
            # Nesting `_lock` here is safe — clear() never holds both at once.
            with _lock:
                stale = epoch != _lifecycle_epoch or _shutdown_requested
            if stale:
                logger.debug("Agent models catalog save skipped (stale epoch)")
                return
            models_storage.save(new_etag, data)
    except Exception as exc:
        # Transport failures keep the stale catalog: a dropdown populated from
        # last launch beats an empty one.
        logger.debug("Agent models catalog refresh failed: %s", exc)
    finally:
        with _lock:
            if epoch == _lifecycle_epoch:
                _is_loading = False


def _schedule_populate(epoch: int, data: Dict[str, Any]) -> None:
    """Apply the payload on the main thread.

    The `_shutdown_requested` check and the timer registration happen under
    `_lock` together — otherwise a late worker can register a timer after
    unregister() has already removed them.
    """
    import bpy

    def _apply():
        with _lock:
            if epoch != _lifecycle_epoch or _shutdown_requested:
                return None
        model_suggestions.populate_from_payload(data)
        _refresh_preference()
        _redraw()
        return None  # Don't repeat

    with _lock:
        if _shutdown_requested:
            return
        bpy.app.timers.register(_apply, first_interval=0.0)


def _refresh_preference() -> None:
    """Re-read the saved hosted-model pick whenever the catalog CHANGES.

    Only from the network path, never from `load_from_disk()`: bootstrap phase 3
    runs before the login hook, so a disk restore would spend a guaranteed 401.

    A catalog swap is exactly when the pick can have gone stale — `eligible` is
    derived per caller, and a model can be retired from under a saved
    preference. The endpoint is `no-store` and tiny, so there is no ETag to
    revalidate and no timer to hang it off. A 304 reaches neither this nor
    `populate`, which is the point: an unchanged catalog costs nothing.
    """
    try:
        from . import preference_state

        preference_state.refresh()
    except Exception as exc:  # noqa: BLE001 — never break a catalog swap
        logger.debug("Agent model preference refresh failed: %s", exc)


def _redraw() -> None:
    try:
        from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

        trigger_ui_redraw()
    except Exception as exc:
        logger.debug("Agent models catalog redraw failed: %s", exc)
