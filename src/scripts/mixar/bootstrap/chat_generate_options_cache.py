# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixie Chat Generate-options Cache Module.

Caches ``GET /api/v1/generation-catalog/chat-options`` — the
backend-curated subset of generation-catalog services that Mixie chat's
Generate mode supports (service keys, labels, live model lists, credit
costs). This drives the chat composer's catalog-driven Generate Type
dropdown (``scene.mixie_chat_generate_type``), the same way
``generation_catalog_cache`` drives the moodboard tabs.

Behaviour (mirrors the proven generation_catalog_cache architecture):
- ``register()`` loads the last persisted payload from disk (instant,
  stale-while-revalidate) and schedules a background fetch ~2s after
  startup via ``bpy.app.timers``.
- All cache state lives behind a module lock; the background thread only
  holds the lock for guard checks and the final swap — never during I/O.
- Revalidation sends ``If-None-Match`` with the last ``ETag``; a ``304``
  keeps the current payload, a ``200`` swaps it, persists it to disk and
  redraws the UI so open chat composers pick up the new options.
- ``clear_chat_generate_options_cache()`` on logout,
  ``refresh_chat_generate_options_cache()`` on login / manual refresh.

When no payload is available (fresh install, offline, logged out) the
enum helper falls back to ``FALLBACK_OPTIONS`` — a static mirror of the
backend's chat service list — so the dropdown stays usable and every
identifier is still a real service key.
"""

import json
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

logger = get_logger(__name__)

_DISK_FILENAME = "chat_generate_options.json"

# Module-level cache — all reads and writes must be protected by _lock to
# prevent TOCTOU races between the background fetch thread and main-thread
# enum callbacks / draw code.
_lock = threading.Lock()
_options_data: Optional[Dict[str, Any]] = None  # the response "data" object
_etag: Optional[str] = None
_cache_error: Optional[str] = None
_is_loading: bool = False
_shutdown_requested: bool = False

# Per-service icon for the Generate Type dropdown (Blender icon names).
# The C++ footer reads the icon straight off the enum item, so this map is
# the single place a chat service's icon is chosen.
_SERVICE_ICONS = {
    "image_gen": 'IMAGE_DATA',
    "depth_to_image": 'SCENE_DATA',
    "model_3d": 'MESH_CUBE',
    "image_to_3d": 'MESH_ICOSPHERE',
    "hunyuan_rapid": 'MESH_UVSPHERE',
    "pbr_gen": 'SPHERE',
    "scene_reconstruction": 'SCENE',
}
_DEFAULT_ICON = 'PRESET'

# Static mirror of the backend's CHAT_GENERATE_SERVICE_KEYS view — the
# last-resort fallback so the dropdown never renders empty / LOADING
# identifiers. Labels match the generation catalog's service labels.
FALLBACK_OPTIONS: Tuple[Dict[str, Any], ...] = (
    {"service_key": "image_gen", "label": "Text to Image"},
    {"service_key": "model_3d", "label": "Image to 3D"},
    {"service_key": "image_to_3d", "label": "Image to 3D Pro"},
    {"service_key": "hunyuan_rapid", "label": "Rapid 3D"},
    {"service_key": "depth_to_image", "label": "From Blockout"},
    {"service_key": "pbr_gen", "label": "PBR Textures"},
    {"service_key": "scene_reconstruction", "label": "Scene Reconstruction"},
)


# ============================================================================
# DISK PERSISTENCE
# ============================================================================


def _data_dir() -> str:
    """Per-user Mixar data dir (same location the catalog cache uses)."""
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
    global _options_data, _etag
    path = _disk_path()
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        data = stored.get("data") if isinstance(stored, dict) else None
        if not isinstance(data, dict) or not data.get("options"):
            return False
        with _lock:
            _options_data = data
            _etag = stored.get("etag") or None
        logger.info(
            "Chat generate options loaded from disk cache (version=%s)",
            data.get("catalog_version", "?"),
        )
        return True
    except Exception as exc:
        logger.warning("Chat generate options disk cache read failed: %s", exc)
        return False


def _save_to_disk(etag: Optional[str], data: Dict[str, Any]) -> None:
    """Persist the payload + etag. Never raises."""
    path = _disk_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"etag": etag, "data": data}, fh)
    except Exception as exc:
        logger.warning("Chat generate options disk cache write failed: %s", exc)


def _delete_disk_cache() -> None:
    try:
        path = _disk_path()
        if os.path.isfile(path):
            os.remove(path)
    except Exception as exc:
        logger.warning("Chat generate options disk cache delete failed: %s", exc)


# ============================================================================
# TYPED ACCESSORS
# ============================================================================


def is_loaded() -> bool:
    """True when a payload (fresh or persisted) is available."""
    with _lock:
        return _options_data is not None


def is_cache_loading() -> bool:
    with _lock:
        return _is_loading


def get_cache_error() -> Optional[str]:
    with _lock:
        return _cache_error


def get_catalog_version() -> Optional[str]:
    with _lock:
        if _options_data:
            return _options_data.get("catalog_version")
    return None


def get_options() -> List[Dict[str, Any]]:
    """The backend's chat generate options (already filtered + ordered).

    Falls back to ``FALLBACK_OPTIONS`` when nothing is loaded so callers
    always see a usable, service-key-identified list.
    """
    with _lock:
        options = (_options_data or {}).get("options")
    if options:
        return options
    return [dict(opt) for opt in FALLBACK_OPTIONS]


def get_option(service_key: str) -> Optional[Dict[str, Any]]:
    for opt in get_options():
        if opt.get("service_key") == service_key:
            return opt
    return None


def get_service_keys() -> List[str]:
    return [o.get("service_key") for o in get_options() if o.get("service_key")]


def get_default_model_slug(service_key: str) -> Optional[str]:
    """Default (or first) model slug for a chat service, None when unknown."""
    opt = get_option(service_key)
    if not opt:
        return None
    default = opt.get("default_model")
    if default:
        return default
    models = opt.get("models") or []
    if models:
        return models[0].get("slug")
    return None


# ============================================================================
# ENUM ITEM HELPERS
# ============================================================================


def get_generate_type_enum_items() -> List[Tuple[str, str, str, str, int]]:
    """(id, label, desc, icon, value) tuples for the Generate Type enums.

    Identifiers are generation-catalog service keys. The C++ chat footer
    renders each item's icon directly, so icons are assigned here (single
    source). Enum value ints follow list order — every consumer goes
    through identifiers, so ordering changes are cosmetic only.
    """
    items = []
    for idx, opt in enumerate(get_options()):
        key = opt.get("service_key") or ""
        if not key:
            continue
        label = opt.get("label") or key
        cost = opt.get("credit_cost")
        desc = f"{label} ({cost} credits)" if cost is not None else label
        icon = _SERVICE_ICONS.get(key, _DEFAULT_ICON)
        items.append((key, label, desc, icon, idx))
    if not items:  # unreachable while FALLBACK_OPTIONS is non-empty
        items = [("image_gen", "Text to Image", "Text to Image",
                  _SERVICE_ICONS["image_gen"], 0)]
    return items


def resolve_service_key(selected: str) -> str:
    """Map an enum value to a valid chat service key.

    Returns *selected* when it names one of the current options, the first
    option's key otherwise (covers placeholder / stale saved values).
    """
    keys = get_service_keys()
    if selected in keys:
        return selected
    return keys[0] if keys else "image_gen"


# ============================================================================
# LIFECYCLE / FETCH
# ============================================================================


def clear_chat_generate_options_cache() -> None:
    """Clear cached data without re-fetching (e.g. on logout).

    Also removes the disk persistence so the next user on this machine
    doesn't render another account's options.
    """
    global _options_data, _etag, _cache_error
    with _lock:
        _options_data = None
        _etag = None
        _cache_error = None
    _delete_disk_cache()


def refresh_chat_generate_options_cache() -> None:
    """Manually trigger an async (re)validation of the cache."""
    with _lock:
        if _shutdown_requested or _is_loading:
            return  # Fetch already in progress; avoid concurrent hazard

    threading.Thread(
        target=_fetch_data_sync,
        daemon=True,
        name="MixarChatGenerateOptionsRefresh",
    ).start()


def _fetch_data_sync() -> None:
    """Fetch/revalidate the options in a background thread.

    Holds _lock only for the guard and the final swap — never during
    network I/O — so readers keep seeing the old payload mid-flight.
    An already-loaded cache does NOT skip the fetch: the If-None-Match
    revalidation is the point (304 = keep, 200 = swap).
    """
    global _options_data, _etag, _cache_error, _is_loading

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
            logger.debug("Skipping chat generate options fetch: not authenticated")
        else:
            from mixar.modules.common.api.services.generation_catalog_service import (
                get_generation_catalog_service,
            )

            service = get_generation_catalog_service()
            response = service.get_chat_options(etag=etag)

            if response.status_code == 304:
                logger.info("Chat generate options unchanged (304 Not Modified)")
            elif response.success and isinstance(response.data, dict):
                data = response.data.get("data") or {}
                if isinstance(data, dict) and data.get("options"):
                    new_etag = response.headers.get("ETag") or response.headers.get("etag")
                    with _lock:
                        if _shutdown_requested:
                            return
                        _options_data = data
                        _etag = new_etag
                    _save_to_disk(new_etag, data)
                    swapped = True
                    logger.info(
                        "Chat generate options loaded (version=%s, %d options)",
                        data.get("catalog_version", "?"),
                        len(data.get("options") or []),
                    )
                else:
                    new_error = "Chat options response missing options"
                    logger.warning("[ChatGenerateOptions] %s", new_error)
            else:
                new_error = (
                    f"Chat options API returned status={getattr(response, 'status_code', '?')}"
                )
                logger.warning("[ChatGenerateOptions] %s", new_error)

    except Exception as exc:
        new_error = f"Chat options fetch failed: {exc}"
        logger.error("[ChatGenerateOptions] %s", new_error)

    finally:
        with _lock:
            _cache_error = new_error
            _is_loading = False
            do_notify = swapped and not _shutdown_requested
        if do_notify:
            _schedule_redraw()


def _schedule_redraw() -> None:
    """Schedule a UI redraw on the main thread (idempotent)."""
    try:
        import bpy

        if not bpy.app.timers.is_registered(trigger_ui_redraw):
            bpy.app.timers.register(trigger_ui_redraw, first_interval=0.0)
    except Exception:
        pass


# ============================================================================
# REGISTRATION (bootstrap contract)
# ============================================================================


def _start_background_fetch() -> None:
    """Timer callback: kick off the background fetch thread (main thread)."""
    threading.Thread(
        target=_fetch_data_sync, daemon=True, name="MixarChatGenerateOptionsCache"
    ).start()
    return None  # Don't repeat


# Periodic revalidation cadence — same rationale as the catalog cache: an
# unchanged payload costs one 304 round-trip, dashboard edits reach a
# RUNNING Blender within this window.
_REVALIDATE_INTERVAL_S = 180.0


def _periodic_revalidate() -> float:
    """Repeating timer: revalidate the options against the backend."""
    with _lock:
        if _shutdown_requested:
            return _REVALIDATE_INTERVAL_S  # unregistered on shutdown anyway
        busy = _is_loading
    if not busy:
        threading.Thread(
            target=_fetch_data_sync,
            daemon=True,
            name="MixarChatGenerateOptionsRevalidate",
        ).start()
    return _REVALIDATE_INTERVAL_S  # repeat


def register() -> None:
    """Called by bootstrap during startup.

    Loads the persisted payload synchronously (instant stale render) and
    schedules the background revalidation ~2s after startup.
    """
    global _shutdown_requested
    import bpy

    with _lock:
        _shutdown_requested = False

    _load_from_disk()

    if not bpy.app.timers.is_registered(_start_background_fetch):
        bpy.app.timers.register(_start_background_fetch, first_interval=2.0)
    if not bpy.app.timers.is_registered(_periodic_revalidate):
        bpy.app.timers.register(
            _periodic_revalidate, first_interval=_REVALIDATE_INTERVAL_S
        )


def unregister() -> None:
    """Called by bootstrap during shutdown."""
    global _options_data, _etag, _cache_error, _is_loading, _shutdown_requested
    with _lock:
        _shutdown_requested = True

    try:
        import bpy

        for cb in (_start_background_fetch, _periodic_revalidate):
            if bpy.app.timers.is_registered(cb):
                bpy.app.timers.unregister(cb)
        if bpy.app.timers.is_registered(trigger_ui_redraw):
            bpy.app.timers.unregister(trigger_ui_redraw)
    except Exception:
        pass

    with _lock:
        _options_data = None
        _etag = None
        _cache_error = None
        _is_loading = False
