# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stale-while-revalidate cache for ``GET /api/v1/generation-catalog``.

The catalog describes capabilities, services, models, parameter schemas,
styles, and credit costs. Startup loads its persisted payload before a delayed
ETag revalidation; successful swaps rebuild dynamic parameters and redraw the
UI. A lifecycle epoch prevents late workers from repopulating data after
logout/unregister. Persistence uses Blender's per-user Mixar data directory,
with ``~/.mixar`` as a fallback.
"""

import threading
from typing import Any, Dict, List, Optional, Tuple

from mixar.bootstrap.generation_catalog import storage as generation_catalog_storage
from mixar.bootstrap.generation_catalog.queries import GenerationCatalogQueries
from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

logger = get_logger(__name__)

# Module-level cache — all reads and writes must be protected by _lock to
# prevent TOCTOU races between the background fetch thread and main-thread
# enum callbacks / draw code.
_lock = threading.Lock()
# Disk I/O is serialized separately so logout cannot race a stale worker's
# save, while UI readers are not blocked behind fsync/replace.
_persistence_lock = threading.Lock()
_catalog: Optional[Dict[str, Any]] = None  # the response "data" object
_etag: Optional[str] = None
_cache_error: Optional[str] = None
_is_loading: bool = False
_shutdown_requested: bool = False
# Monotonic lifecycle token.  Every logout/register/unregister invalidates
# workers started by the previous lifecycle so a late response can never
# repopulate another user's cache (or reset a newer worker's loading state).
_lifecycle_epoch: int = 0

# EnumProperty ``items`` callbacks MUST keep a persistent Python reference to
# the strings they return — Blender stores the raw ``char*`` and will render
# garbage or crash if the strings are garbage-collected. Building a fresh list
# on every callback (they fire on every redraw) is exactly that hazard. Cache
# each built list keyed by (kind, key, version); ``_enum_version`` bumps on
# every catalog swap/clear (always under ``_lock``) so callers get a stable,
# strongly-referenced object that is only rebuilt when the catalog changes.
_enum_version: int = 0
_enum_cache: Dict[Tuple[str, str, int], List[Tuple[str, str, str]]] = {}

# Placeholder item lists are module-level constants (not rebuilt per call) so
# their strings also outlive the callback.
_ENUM_LOADING = [("LOADING", "Loading...", "Fetching generation catalog")]


def _catalog_snapshot() -> Optional[Dict[str, Any]]:
    with _lock:
        return _catalog


_queries = GenerationCatalogQueries(_catalog_snapshot)


def _bump_enum_version_locked() -> None:
    """Invalidate the enum-item cache. Caller MUST hold ``_lock``."""
    global _enum_version
    _enum_version += 1


def _enum_cached(kind: str, key: str, version: int, builder):
    """Return a memoized enum-item list, holding a persistent reference.

    Rebuilds via ``builder()`` only when this (kind, key, version) is unseen,
    then prunes entries from versions older than the previous one (Blender may
    still hold ``char*`` into the immediately-previous version during a redraw).
    """
    cache_key = (kind, key, version)
    cached = _enum_cache.get(cache_key)
    if cached is not None:
        return cached
    items = builder()
    _enum_cache[cache_key] = items
    stale = [k for k in _enum_cache if k[2] < version - 1]
    for k in stale:
        del _enum_cache[k]
    return items


def memoize_enum_items(kind: str, key: str, builder):
    """Memoize an EnumProperty ``items`` list built by other modules.

    Public wrapper around the internal enum cache so callers outside this
    module (e.g. ``generation_params.selector``) can return persistently
    referenced lists too. ``builder()`` runs only when this (kind, key)
    is unseen for the current catalog version. Enum callbacks run on the
    main thread, so the cache dict itself needs no extra lock.
    """
    with _lock:
        version = _enum_version
    return _enum_cached(kind, key, version, builder)


def _load_from_disk() -> bool:
    """Populate the in-memory cache from the persisted payload, if any.

    Returns True when a payload was loaded. Never raises.
    """
    global _catalog, _etag
    loaded = generation_catalog_storage.load()
    if loaded is None:
        return False
    data, etag = loaded
    with _lock:
        _catalog = data
        _etag = etag
        _bump_enum_version_locked()
    logger.info(
        "Generation catalog loaded from disk cache (version=%s)",
        data.get("catalog_version", "?"),
    )
    return True


# ============================================================================
# TYPED ACCESSORS
# ============================================================================


def is_loaded() -> bool:
    """True when a catalog payload (fresh or persisted) is available."""
    with _lock:
        return _catalog is not None


def is_cache_loading() -> bool:
    with _lock:
        return _is_loading


def get_cache_error() -> Optional[str]:
    with _lock:
        return _cache_error


def get_catalog_version() -> Optional[str]:
    with _lock:
        if _catalog:
            return _catalog.get("catalog_version")
    return None


get_capabilities = _queries.get_capabilities
get_capability = _queries.get_capability
get_capability_for_service = _queries.get_capability_for_service
get_services = _queries.get_services
get_service = _queries.get_service
get_models = _queries.get_models
get_model = _queries.get_model
get_default_model_slug = _queries.get_default_model_slug
get_styles = _queries.get_styles
get_credit_cost = _queries.get_credit_cost


# ============================================================================
# ENUM ITEM HELPERS
# ============================================================================


def get_model_enum_items(service_key: str) -> List[Tuple[str, str, str]]:
    """(id, label, desc) tuples for a service's models, with LOADING/ERROR
    placeholder states matching the existing caches."""
    with _lock:
        loading = _is_loading
        loaded = _catalog is not None
        error = _cache_error
        version = _enum_version

    if not loaded:
        if loading:
            return _ENUM_LOADING
        if error:
            return _enum_cached("model_err", error, version,
                                lambda: [("ERROR", "Error", error)])
        return _ENUM_LOADING

    def _build():
        models = get_models(service_key)
        if not models:
            return [("NONE", "No models", "No models available")]
        built = []
        for m in models:
            slug = m.get("slug") or ""
            label = m.get("label") or slug
            cost = m.get("credit_cost")
            desc = f"{label} ({cost} credits)" if cost is not None else label
            built.append((slug, label, desc))
        return built

    return _enum_cached("model", service_key, version, _build)


def get_style_enum_items(generation_type: str) -> List[Tuple[str, str, str]]:
    """(id, label, desc) tuples for a generation type's styles."""
    with _lock:
        loading = _is_loading
        loaded = _catalog is not None
        error = _cache_error
        version = _enum_version

    if not loaded:
        if loading:
            return _ENUM_LOADING
        if error:
            return _enum_cached("style_err", error, version,
                                lambda: [("ERROR", "Error", error)])
        return _ENUM_LOADING

    def _build():
        styles = get_styles(generation_type)
        if not styles:
            return [("NONE", "No styles", "No styles available")]
        return [
            (
                s.get("name") or "NONE",
                s.get("display_name") or s.get("name") or "Unknown",
                s.get("description") or "",
            )
            for s in styles
            if s.get("name")
        ]

    return _enum_cached("style", generation_type, version, _build)


# ============================================================================
# LIFECYCLE / FETCH
# ============================================================================


def clear_generation_catalog_cache() -> None:
    """Clear cached data without re-fetching (e.g. on logout).

    Also removes the disk persistence so the next user on this machine
    doesn't render another account's catalog.
    """
    global _catalog, _etag, _cache_error, _is_loading, _lifecycle_epoch
    with _lock:
        _lifecycle_epoch += 1
        _catalog = None
        _etag = None
        _cache_error = None
        _is_loading = False
        _bump_enum_version_locked()
    # Serialize deletion with a worker's guarded atomic save. Once this lock
    # is acquired, no invalidated worker can recreate the file afterward.
    with _persistence_lock:
        generation_catalog_storage.delete()


def refresh_generation_catalog_cache() -> None:
    """Manually trigger an async (re)validation of the cache."""
    with _lock:
        if _shutdown_requested or _is_loading:
            return  # Fetch already in progress; avoid concurrent hazard

    threading.Thread(
        target=_fetch_data_sync,
        daemon=True,
        name="MixarGenerationCatalogRefresh",
    ).start()


def _on_catalog_swapped() -> None:
    """Main-thread timer callback after a new payload was swapped in.

    Rebuilds the dynamic parameter engine (when present) and redraws all
    areas. Returns None so the timer does not repeat.
    """
    try:
        from mixar.modules.common.generation_params.core.engine import (
            rebuild_from_catalog,
        )

        rebuild_from_catalog()
    except ImportError:
        pass
    except Exception as exc:
        logger.error("Generation param engine rebuild failed: %s", exc)
    trigger_ui_redraw()
    return None


def _schedule_catalog_swapped() -> None:
    """Schedule _on_catalog_swapped on the main thread (idempotent)."""
    try:
        import bpy

        # Keep the lifecycle check and registration atomic with unregister().
        # A fetch may finish after shutdown has begun; without the lock it can
        # recreate this timer after unregister() has already removed it.
        with _lock:
            if _shutdown_requested:
                return
            if not bpy.app.timers.is_registered(_on_catalog_swapped):
                bpy.app.timers.register(_on_catalog_swapped, first_interval=0.0)
    except Exception:
        pass


def _fetch_data_sync() -> None:
    """Fetch/revalidate the catalog in a background thread.

    Holds _lock only for the guard and the final swap — never during
    network I/O — so readers keep seeing the old payload mid-flight.
    Unlike imagegen_cache, an already-loaded cache does NOT skip the fetch:
    the If-None-Match revalidation is the point (304 = keep, 200 = swap).
    """
    global _catalog, _etag, _cache_error, _is_loading

    with _lock:
        if _shutdown_requested or _is_loading:
            return
        _is_loading = True
        etag = _etag
        epoch = _lifecycle_epoch

    new_error: Optional[str] = None
    swapped = False

    try:
        from mixar.modules.auth.core.auth import get_access_token

        if not get_access_token():
            logger.debug("Skipping generation catalog fetch: not authenticated")
        else:
            from mixar.modules.common.api.services.generation_catalog_service import (
                get_generation_catalog_service,
            )

            service = get_generation_catalog_service()
            response = service.get_catalog(etag=etag)

            if response.status_code == 304:
                logger.info("Generation catalog unchanged (304 Not Modified)")
            elif response.success and isinstance(response.data, dict):
                data = response.data.get("data")
                capabilities = data.get("capabilities") if isinstance(data, dict) else None
                # An empty list is authoritative: it is the backend's kill
                # switch for all generation capabilities, not a malformed
                # response that should leave stale services visible.
                if isinstance(data, dict) and isinstance(capabilities, list):
                    new_etag = response.headers.get("ETag") or response.headers.get("etag")
                    with _persistence_lock:
                        with _lock:
                            if _shutdown_requested or epoch != _lifecycle_epoch:
                                return
                            _catalog = data
                            _etag = new_etag
                            _bump_enum_version_locked()
                        generation_catalog_storage.save(new_etag, data)
                    swapped = True
                    logger.info(
                        "Generation catalog loaded (version=%s, %d capabilities)",
                        data.get("catalog_version", "?"),
                        len(capabilities),
                    )
                else:
                    new_error = "Catalog response missing capabilities"
                    logger.warning("[GenerationCatalog] %s", new_error)
            else:
                new_error = (
                    f"Catalog API returned status={getattr(response, 'status_code', '?')}"
                )
                logger.warning("[GenerationCatalog] %s", new_error)

    except Exception as exc:
        new_error = f"Catalog fetch failed: {exc}"
        logger.error("[GenerationCatalog] %s", new_error)

    finally:
        with _lock:
            if epoch == _lifecycle_epoch:
                _cache_error = new_error
                _is_loading = False
                do_notify = swapped and not _shutdown_requested
            else:
                do_notify = False
        if do_notify:
            _schedule_catalog_swapped()


# ============================================================================
# REGISTRATION (bootstrap contract)
# ============================================================================


def _start_background_fetch() -> None:
    """Timer callback: kick off the background fetch thread (main thread)."""
    threading.Thread(
        target=_fetch_data_sync, daemon=True, name="MixarGenerationCatalogCache"
    ).start()
    return None  # Don't repeat


# Periodic revalidation cadence. The check sends If-None-Match, so an
# unchanged catalog costs one 304 round-trip — dashboard edits (disabled
# tabs, new models, price changes) reach a RUNNING Blender within this
# window instead of waiting for a restart/login/manual refresh.
_REVALIDATE_INTERVAL_S = 180.0


def _periodic_revalidate() -> float:
    """Repeating timer: revalidate the catalog against the backend."""
    with _lock:
        if _shutdown_requested:
            return _REVALIDATE_INTERVAL_S  # unregistered on shutdown anyway
        busy = _is_loading
    if not busy:
        threading.Thread(
            target=_fetch_data_sync,
            daemon=True,
            name="MixarGenerationCatalogRevalidate",
        ).start()
    return _REVALIDATE_INTERVAL_S  # repeat


def register() -> None:
    """Called by bootstrap during startup.

    Loads the persisted payload synchronously (instant stale render) and
    schedules the background revalidation ~2s after startup.
    """
    global _shutdown_requested, _is_loading, _lifecycle_epoch
    import bpy

    generation_catalog_storage.initialize_disk_path()

    with _lock:
        _lifecycle_epoch += 1
        _shutdown_requested = False
        _is_loading = False

    if _load_from_disk():
        # Rebuild the parameter engine from the stale payload right away so
        # the panel renders instantly; revalidation may swap it shortly.
        _schedule_catalog_swapped()

    if not bpy.app.timers.is_registered(_start_background_fetch):
        bpy.app.timers.register(_start_background_fetch, first_interval=2.0)
    if not bpy.app.timers.is_registered(_periodic_revalidate):
        bpy.app.timers.register(
            _periodic_revalidate, first_interval=_REVALIDATE_INTERVAL_S
        )


def unregister() -> None:
    """Called by bootstrap during shutdown."""
    global _catalog, _etag, _cache_error, _is_loading, _shutdown_requested, _lifecycle_epoch
    with _lock:
        _lifecycle_epoch += 1
        _shutdown_requested = True
        _is_loading = False

    try:
        import bpy

        for cb in (_start_background_fetch, _on_catalog_swapped, _periodic_revalidate):
            if bpy.app.timers.is_registered(cb):
                bpy.app.timers.unregister(cb)
        if bpy.app.timers.is_registered(trigger_ui_redraw):
            bpy.app.timers.unregister(trigger_ui_redraw)
    except Exception:
        pass

    try:
        from mixar.modules.common.generation_params.core.engine import (
            unregister_all_param_groups,
        )

        unregister_all_param_groups()
    except Exception:
        pass

    with _lock:
        _catalog = None
        _etag = None
        _cache_error = None
        _is_loading = False
        _bump_enum_version_locked()
