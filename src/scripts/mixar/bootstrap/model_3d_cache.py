# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Model 3D Cache Module.

Caches available 3D generation models for use in dynamic dropdowns.
Models are fetched asynchronously in a background thread at startup.
"""

import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

logger = get_logger(__name__)


# ============================================================================
# MODEL CACHE DATA STRUCTURES
# ============================================================================


@dataclass
class Model3DInfo:
    """Information about a 3D generation model."""

    name: str  # API identifier (e.g., "trellis-1")
    display_name: str  # UI display name (e.g., "Trellis 1.0")
    credit_cost: int  # Credits per generation


# Module-level cache — all reads and writes must be protected by _lock to
# prevent TOCTOU races between the background fetch thread and main-thread
# enum callbacks.
_lock = threading.Lock()
_cached_models: Optional[List[Model3DInfo]] = None
_cache_error: Optional[str] = None
_is_loading: bool = False
_shutdown_requested: bool = False


# ============================================================================
# CACHE ACCESS FUNCTIONS
# ============================================================================


def get_cached_models() -> Optional[List[Model3DInfo]]:
    """Get the cached list of 3D models, or None if not yet loaded."""
    with _lock:
        return _cached_models


def get_default_model_name() -> Optional[str]:
    """Get the first/default model name from cache.

    Returns None before the background fetch completes (approximately 2 seconds
    after startup). Callers must handle None gracefully — defer UI updates or
    fall back to a hardcoded default until the cache is populated.
    """
    with _lock:
        if _cached_models:
            return _cached_models[0].name
    return None


def get_cache_error() -> Optional[str]:
    """Get any error that occurred during model fetching."""
    with _lock:
        return _cache_error


def is_cache_loading() -> bool:
    """Check if models are currently being fetched."""
    with _lock:
        return _is_loading


def get_model_enum_items(
    self=None, context=None
) -> List[Tuple[str, str, str]]:
    """Callback function for dynamic EnumProperty items.

    Returns list of tuples: (identifier, name, description)
    """
    with _lock:
        loading = _is_loading
        models = _cached_models
        error = _cache_error

    if loading or models is None:
        return [("LOADING", "Loading...", "Fetching available models")]

    # Return error placeholder if fetch failed and no models
    if error and not models:
        return [("ERROR", "Error", error)]

    # Return cached models if available
    if models:
        return [
            (m.name, m.display_name, f"{m.display_name} ({m.credit_cost} credits)")
            for m in models
        ]

    # Fallback if cache is empty
    return [("NONE", "No models", "No 3D generation models available")]


def clear_models_cache() -> None:
    """Clear cached data without re-fetching (e.g. on logout)."""
    global _cached_models, _cache_error

    with _lock:
        _cached_models = None
        _cache_error = None


def refresh_models_cache() -> None:
    """Manually trigger an async refresh of the models cache."""
    global _cached_models

    with _lock:
        if _shutdown_requested or _is_loading:
            return  # Fetch already in progress; avoid concurrent hazard
        _cached_models = None

    threading.Thread(
        target=_fetch_models_sync, daemon=True, name="MixarModel3DCacheRefresh"
    ).start()


# ============================================================================
# INTERNAL FUNCTIONS
# ============================================================================


def _fetch_models_sync() -> None:
    """Fetch models in a background thread.

    Acquires _lock only for the initial guard (check + set _is_loading) and
    the final write — not during network I/O — so enum callbacks can still
    read the old cache while the fetch is in flight.

    Always sets _cached_models to at least [] on failure, preventing a
    retry-on-every-UI-draw loop that would freeze the UI.
    """
    global _cached_models, _cache_error, _is_loading

    with _lock:
        if _shutdown_requested or _cached_models is not None or _is_loading:
            return  # Already loaded or loading
        _is_loading = True

    new_models: List[Model3DInfo] = []
    new_error: Optional[str] = None
    _skipped = False

    try:
        from mixar.modules.auth.core.auth import get_access_token

        if not get_access_token():
            logger.debug("Skipping Model3D config fetch: not authenticated")
            _skipped = True
        else:
            from mixar.modules.common.api import get_model_3d_gen_service

            service = get_model_3d_gen_service()
            response = service.get_models()

            if response.success and response.data:
                data = response.data
                if isinstance(data, dict) and "data" in data:
                    data = data["data"]

                for m in data.get("models", []):
                    if not m.get("name"):
                        continue
                    new_models.append(Model3DInfo(
                        name=m.get("name", ""),
                        display_name=m.get("display_name", m.get("name", "Unknown")),
                        credit_cost=m.get("credit_cost", 0),
                    ))
                logger.info(f"Loaded {len(new_models)} 3D generation models")
            else:
                new_error = f"Models API returned status={getattr(response, 'status_code', '?')}"
                logger.error(f"[Model3D] {new_error}")

    except Exception as e:
        new_error = str(e)
        logger.error(f"Model 3D cache error: {e}")

    finally:
        if _skipped:
            with _lock:
                _is_loading = False
        else:
            with _lock:
                _cached_models = new_models
                _cache_error = new_error
                _is_loading = False

                # Schedule while holding the lifecycle lock so unregister()
                # cannot miss a redraw timer created by a late background fetch.
                try:
                    import bpy
                    if (
                        not _shutdown_requested
                        and not bpy.app.timers.is_registered(trigger_ui_redraw)
                    ):
                        bpy.app.timers.register(trigger_ui_redraw, first_interval=0.0)
                except Exception:
                    pass


# ============================================================================
# REGISTRATION (kept for bootstrap compatibility)
# ============================================================================


def _start_background_fetch() -> None:
    """Timer callback: kick off the background fetch thread (runs on main thread)."""
    threading.Thread(
        target=_fetch_models_sync, daemon=True, name="MixarModel3DCache"
    ).start()
    return None  # Don't repeat


def register() -> None:
    """Called by bootstrap during startup. Schedules async cache population."""
    global _shutdown_requested
    import bpy

    with _lock:
        _shutdown_requested = False

    if not bpy.app.timers.is_registered(_start_background_fetch):
        bpy.app.timers.register(_start_background_fetch, first_interval=2.0)


def unregister() -> None:
    """Called by bootstrap during shutdown."""
    global _cached_models, _cache_error, _is_loading, _shutdown_requested
    with _lock:
        _shutdown_requested = True

    try:
        import bpy
        if bpy.app.timers.is_registered(_start_background_fetch):
            bpy.app.timers.unregister(_start_background_fetch)
        if bpy.app.timers.is_registered(trigger_ui_redraw):
            bpy.app.timers.unregister(trigger_ui_redraw)
    except Exception:
        pass

    with _lock:
        _cached_models = None
        _cache_error = None
        _is_loading = False
