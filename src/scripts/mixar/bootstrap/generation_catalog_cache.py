# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Generation Catalog Cache Module.

Caches the unified generation catalog (``GET /api/v1/generation-catalog``)
that describes all generation capabilities, their services, models,
parameter schemas, styles and credit costs. This is the successor of the
per-feature ``imagegen_cache.py`` / ``model_3d_cache.py`` pattern — those
files were retired (Stage 3); every consumer now reads this cache with
static hardcoded lists as last-resort fallbacks.

Behaviour (mirrors the proven imagegen_cache architecture):
- ``register()`` loads the last persisted payload from disk (instant,
  stale-while-revalidate) and schedules a background fetch ~2s after
  startup via ``bpy.app.timers``.
- All cache state lives behind a module lock; the background thread only
  holds the lock for guard checks and the final swap — never during I/O.
- Revalidation sends ``If-None-Match`` with the last ``ETag``; a ``304``
  keeps the current payload, a ``200`` swaps it, persists it to disk and
  redraws MIXIE areas (plus rebuilds the dynamic parameter engine).
- ``clear_generation_catalog_cache()`` on logout, manual
  ``refresh_generation_catalog_cache()`` for the refresh buttons / login.

Disk persistence uses the same per-user Mixar data dir as the onboarding
persistence: ``bpy.utils.user_resource('DATAFILES', path='mixar')`` with a
``~/.mixar`` fallback.
"""

import json
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

logger = get_logger(__name__)

_DISK_FILENAME = "generation_catalog.json"

# Module-level cache — all reads and writes must be protected by _lock to
# prevent TOCTOU races between the background fetch thread and main-thread
# enum callbacks / draw code.
_lock = threading.Lock()
_catalog: Optional[Dict[str, Any]] = None  # the response "data" object
_etag: Optional[str] = None
_cache_error: Optional[str] = None
_is_loading: bool = False
_shutdown_requested: bool = False


# ============================================================================
# DISK PERSISTENCE
# ============================================================================


def _data_dir() -> str:
    """Per-user Mixar data dir (same location onboarding persistence uses)."""
    try:
        import bpy

        path = bpy.utils.user_resource("DATAFILES", path="mixar")
        if path:
            return path
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), ".mixar")


def _disk_path() -> str:
    return os.path.join(_data_dir(), _DISK_FILENAME)


def _load_from_disk() -> bool:
    """Populate the in-memory cache from the persisted payload, if any.

    Returns True when a payload was loaded. Never raises.
    """
    global _catalog, _etag
    path = _disk_path()
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        data = stored.get("data") if isinstance(stored, dict) else None
        if not isinstance(data, dict) or not data.get("capabilities"):
            return False
        with _lock:
            _catalog = data
            _etag = stored.get("etag") or None
        logger.info(
            "Generation catalog loaded from disk cache (version=%s)",
            data.get("catalog_version", "?"),
        )
        return True
    except Exception as exc:
        logger.warning("Generation catalog disk cache read failed: %s", exc)
        return False


def _save_to_disk(etag: Optional[str], data: Dict[str, Any]) -> None:
    """Persist the payload + etag. Never raises."""
    path = _disk_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"etag": etag, "data": data}, fh)
    except Exception as exc:
        logger.warning("Generation catalog disk cache write failed: %s", exc)


def _delete_disk_cache() -> None:
    try:
        path = _disk_path()
        if os.path.isfile(path):
            os.remove(path)
    except Exception as exc:
        logger.warning("Generation catalog disk cache delete failed: %s", exc)


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


def get_capabilities() -> List[Dict[str, Any]]:
    """All capabilities sorted by sort_order. Empty list when not loaded."""
    with _lock:
        caps = (_catalog or {}).get("capabilities") or []
    return sorted(caps, key=lambda c: c.get("sort_order", 0))


def get_capability(capability_key: str) -> Optional[Dict[str, Any]]:
    for cap in get_capabilities():
        if cap.get("key") == capability_key:
            return cap
    return None


def get_services(
    capability_key: str, surface: str = "moodboard"
) -> List[Dict[str, Any]]:
    """Services of a capability filtered by surface, sorted by sort_order.

    Paint-surfaced services (e.g. brush_gen) never appear in moodboard tabs.
    """
    cap = get_capability(capability_key)
    if not cap:
        return []
    services = [
        s for s in (cap.get("services") or [])
        if not surface or s.get("surface") == surface
    ]
    return sorted(services, key=lambda s: s.get("sort_order", 0))


def get_service(service_key: str) -> Optional[Dict[str, Any]]:
    """Look up a service by key across all capabilities (any surface)."""
    for cap in get_capabilities():
        for svc in cap.get("services") or []:
            if svc.get("key") == service_key:
                return svc
    return None


def get_models(service_key: str) -> List[Dict[str, Any]]:
    svc = get_service(service_key)
    if not svc:
        return []
    return svc.get("models") or []


def get_model(service_key: str, slug: str) -> Optional[Dict[str, Any]]:
    for model in get_models(service_key):
        if model.get("slug") == slug:
            return model
    return None


def get_default_model_slug(service_key: str) -> Optional[str]:
    """Default (or first) model slug for a service, None when not loaded."""
    models = get_models(service_key)
    for model in models:
        if model.get("is_default"):
            return model.get("slug")
    if models:
        return models[0].get("slug")
    return None


def get_styles(generation_type: str) -> List[Dict[str, Any]]:
    """Styles for a generation type (e.g. ``"image"``)."""
    with _lock:
        styles = ((_catalog or {}).get("styles") or {}).get(generation_type)
    return styles or []


def get_credit_cost(feature_key: str) -> Optional[int]:
    with _lock:
        costs = (_catalog or {}).get("credit_costs") or {}
    return costs.get(feature_key)


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

    if not loaded:
        if loading:
            return [("LOADING", "Loading...", "Fetching generation catalog")]
        if error:
            return [("ERROR", "Error", error)]
        return [("LOADING", "Loading...", "Fetching generation catalog")]

    models = get_models(service_key)
    if not models:
        return [("NONE", "No models", "No models available")]
    items = []
    for m in models:
        slug = m.get("slug") or ""
        label = m.get("label") or slug
        cost = m.get("credit_cost")
        desc = f"{label} ({cost} credits)" if cost is not None else label
        items.append((slug, label, desc))
    return items


def get_style_enum_items(generation_type: str) -> List[Tuple[str, str, str]]:
    """(id, label, desc) tuples for a generation type's styles."""
    with _lock:
        loading = _is_loading
        loaded = _catalog is not None
        error = _cache_error

    if not loaded:
        if loading:
            return [("LOADING", "Loading...", "Fetching generation catalog")]
        if error:
            return [("ERROR", "Error", error)]
        return [("LOADING", "Loading...", "Fetching generation catalog")]

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


# ============================================================================
# LIFECYCLE / FETCH
# ============================================================================


def clear_generation_catalog_cache() -> None:
    """Clear cached data without re-fetching (e.g. on logout).

    Also removes the disk persistence so the next user on this machine
    doesn't render another account's catalog.
    """
    global _catalog, _etag, _cache_error
    with _lock:
        _catalog = None
        _etag = None
        _cache_error = None
    _delete_disk_cache()


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
                data = response.data.get("data") or {}
                if isinstance(data, dict) and data.get("capabilities"):
                    new_etag = response.headers.get("ETag") or response.headers.get("etag")
                    with _lock:
                        if _shutdown_requested:
                            return
                        _catalog = data
                        _etag = new_etag
                    _save_to_disk(new_etag, data)
                    swapped = True
                    logger.info(
                        "Generation catalog loaded (version=%s, %d capabilities)",
                        data.get("catalog_version", "?"),
                        len(data.get("capabilities") or []),
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
            _cache_error = new_error
            _is_loading = False
            do_notify = swapped and not _shutdown_requested
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


def register() -> None:
    """Called by bootstrap during startup.

    Loads the persisted payload synchronously (instant stale render) and
    schedules the background revalidation ~2s after startup.
    """
    global _shutdown_requested
    import bpy

    with _lock:
        _shutdown_requested = False

    if _load_from_disk():
        # Rebuild the parameter engine from the stale payload right away so
        # the panel renders instantly; revalidation may swap it shortly.
        _schedule_catalog_swapped()

    if not bpy.app.timers.is_registered(_start_background_fetch):
        bpy.app.timers.register(_start_background_fetch, first_interval=2.0)


def unregister() -> None:
    """Called by bootstrap during shutdown."""
    global _catalog, _etag, _cache_error, _is_loading, _shutdown_requested
    with _lock:
        _shutdown_requested = True

    try:
        import bpy

        for cb in (_start_background_fetch, _on_catalog_swapped):
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
