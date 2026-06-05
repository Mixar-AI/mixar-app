# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
ImageGen Cache Module.

Caches available image generation models and styles for use in dynamic dropdowns.
Data is fetched asynchronously in a background thread at startup.
"""

import threading
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

logger = get_logger(__name__)


# ============================================================================
# CACHE DATA STRUCTURES
# ============================================================================


@dataclass
class ImageGenModelInfo:
    """Information about an image generation model."""

    name: str  # API identifier (e.g., "flash")
    display_name: str  # UI display name (e.g., "Gemini 2.5 Flash")
    credit_cost: int  # Credits per generation
    max_reference_images: int  # Maximum reference images allowed
    max_images_per_request: int  # Maximum images per request
    supported_resolutions: List[str] = field(default_factory=list)
    supported_aspect_ratios: List[str] = field(default_factory=list)


@dataclass
class ImageGenStyleInfo:
    """Information about an image generation style."""

    name: str  # API identifier (e.g., "photorealistic")
    display_name: str  # UI display name (e.g., "Photorealistic")
    description: str  # Style description


# Module-level cache — all reads and writes must be protected by _lock to
# prevent TOCTOU races between the background fetch thread and main-thread
# enum callbacks.
_lock = threading.Lock()
_cached_models: Optional[List[ImageGenModelInfo]] = None
_cached_styles: Optional[List[ImageGenStyleInfo]] = None
_cache_error: Optional[str] = None
_is_loading: bool = False
_shutdown_requested: bool = False


# ============================================================================
# CACHE ACCESS FUNCTIONS
# ============================================================================


def get_cached_models() -> Optional[List[ImageGenModelInfo]]:
    """Get the cached list of models, or None if not yet loaded."""
    with _lock:
        return _cached_models


def get_cached_styles() -> Optional[List[ImageGenStyleInfo]]:
    """Get the cached list of styles, or None if not yet loaded."""
    with _lock:
        return _cached_styles


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
    """Get any error that occurred during fetching."""
    with _lock:
        return _cache_error


def is_cache_loading() -> bool:
    """Check if data is currently being fetched."""
    with _lock:
        return _is_loading


def get_model_by_name(model_name: str) -> Optional[ImageGenModelInfo]:
    """Get a specific model by its name."""
    with _lock:
        models = _cached_models
    if models:
        for model in models:
            if model.name == model_name:
                return model
    return None


def get_max_reference_images(model_name: str) -> int:
    """Get maximum reference images for a model (with fallback)."""
    model = get_model_by_name(model_name)
    if model:
        return model.max_reference_images
    # Fallback values if cache not loaded
    return 14 if model_name == "pro" else 3


# ============================================================================
# DYNAMIC ENUM CALLBACKS
# ============================================================================


def get_model_enum_items(
    self=None, context=None
) -> List[Tuple[str, str, str]]:
    """Callback for dynamic model EnumProperty."""
    with _lock:
        loading = _is_loading
        models = _cached_models
        error = _cache_error

    if loading or models is None:
        return [("LOADING", "Loading...", "Fetching available models")]

    if error and not models:
        return [("ERROR", "Error", error)]

    if models:
        return [
            (m.name, m.display_name, f"{m.display_name} ({m.credit_cost} credits)")
            for m in models
        ]

    return [("NONE", "No models", "No models available")]


def get_style_enum_items(
    self=None, context=None
) -> List[Tuple[str, str, str]]:
    """Callback for dynamic style EnumProperty."""
    with _lock:
        loading = _is_loading
        styles = _cached_styles
        error = _cache_error

    if loading or styles is None:
        return [("LOADING", "Loading...", "Fetching available styles")]

    if error and not styles:
        return [("ERROR", "Error", error)]

    if styles:
        return [(s.name, s.display_name, s.description) for s in styles]

    return [("NONE", "No styles", "No styles available")]


def _get_current_model_name(context=None) -> Optional[str]:
    """Get the currently selected model name from context.

    Checks both the global scene property and the sidebar property.
    """
    model_name = None
    try:
        if context and hasattr(context, "scene"):
            scene = context.scene
            # First try sidebar property (new sidebar UI)
            if hasattr(scene, "mixie_moodboard_sidebar"):
                sidebar = scene.mixie_moodboard_sidebar
                if hasattr(sidebar, "tab_imagegen"):
                    model_name = sidebar.tab_imagegen.model
            # Fallback to global property (popup menu)
            if not model_name and hasattr(scene, "mixie_imagegen_model"):
                model_name = scene.mixie_imagegen_model
    except Exception:
        pass
    return model_name


def get_aspect_ratio_enum_items(
    self=None, context=None
) -> List[Tuple[str, str, str]]:
    """Callback for dynamic aspect ratio EnumProperty based on selected model."""
    model_name = _get_current_model_name(context)
    model = get_model_by_name(model_name) if model_name else None

    if model and model.supported_aspect_ratios:
        desc_map = {
            "1:1": "Square",
            "2:3": "Portrait",
            "3:2": "Landscape",
            "3:4": "Portrait Standard",
            "4:3": "Landscape Standard",
            "4:5": "Portrait (Instagram)",
            "5:4": "Landscape (Large)",
            "9:16": "Vertical (Mobile)",
            "16:9": "Widescreen",
            "21:9": "Ultra-wide",
        }
        return [
            (ratio, ratio, desc_map.get(ratio, ratio))
            for ratio in model.supported_aspect_ratios
        ]

    # Fallback
    return [
        ("1:1", "1:1", "Square"),
        ("16:9", "16:9", "Widescreen"),
        ("9:16", "9:16", "Portrait"),
        ("4:3", "4:3", "Standard"),
        ("3:4", "3:4", "Portrait Standard"),
    ]


def get_resolution_enum_items(
    self=None, context=None
) -> List[Tuple[str, str, str]]:
    """Callback for dynamic resolution EnumProperty based on selected model."""
    model_name = _get_current_model_name(context)
    model = get_model_by_name(model_name) if model_name else None

    if model and model.supported_resolutions:
        desc_map = {
            "1K": "1024px (Standard)",
            "2K": "2048px (High Quality)",
            "4K": "4096px (Maximum)",
        }
        return [
            (res, res, desc_map.get(res, res))
            for res in model.supported_resolutions
        ]

    # Fallback - return at least one item
    return [("1K", "1K", "1024px (Standard)")]


def clear_imagegen_cache() -> None:
    """Clear cached data without re-fetching (e.g. on logout)."""
    global _cached_models, _cached_styles, _cache_error

    with _lock:
        _cached_models = None
        _cached_styles = None
        _cache_error = None


def refresh_imagegen_cache() -> None:
    """Manually trigger an async refresh of the cache."""
    global _cached_models, _cached_styles

    with _lock:
        if _shutdown_requested or _is_loading:
            return  # Fetch already in progress; avoid concurrent hazard
        _cached_models = None
        _cached_styles = None

    threading.Thread(
        target=_fetch_data_sync, daemon=True, name="MixarImageGenCacheRefresh"
    ).start()


# ============================================================================
# INTERNAL FUNCTIONS
# ============================================================================


def _fetch_data_sync() -> None:
    """Fetch models and styles in a background thread.

    Acquires _lock only for the initial guard (check + set _is_loading) and
    the final write — not during network I/O — so enum callbacks can still
    read the old cache while the fetch is in flight.

    Always writes _cached_models and _cached_styles (even on failure) so enum
    callbacks never enter an infinite loading loop.
    """
    global _cached_models, _cached_styles, _cache_error, _is_loading

    with _lock:
        if (
            _shutdown_requested
            or (_cached_models is not None and _cached_styles is not None)
            or _is_loading
        ):
            return  # Already loaded or loading
        _is_loading = True

    new_models: List[ImageGenModelInfo] = []
    new_styles: List[ImageGenStyleInfo] = []
    new_error: Optional[str] = None
    _skipped = False

    try:
        from mixar.modules.auth.core.auth import get_access_token

        if not get_access_token():
            logger.debug("Skipping ImageGen config fetch: not authenticated")
            _skipped = True
        else:
            from mixar.modules.common.api.services.generation_metadata_service import (
                get_generation_metadata_service,
            )
            from mixar.modules.common.api.constants import APIModule

            service = get_generation_metadata_service(APIModule.IMAGEGEN)

            # Fetch models
            try:
                models_response = service.get_models()
                if models_response.success and models_response.data:
                    data = models_response.data
                    if isinstance(data, dict) and "data" in data:
                        data = data["data"]

                    for m in data.get("models", []):
                        if not m.get("name"):
                            continue

                        params = m.get("parameters", {})
                        aspect_ratios = params.get("aspect_ratio", {}).get(
                            "enum", m.get("supported_aspect_ratios", ["1:1"])
                        )
                        resolutions = params.get("resolution", {}).get(
                            "enum", m.get("supported_resolutions", [])
                        )

                        new_models.append(ImageGenModelInfo(
                            name=m.get("name", ""),
                            display_name=m.get("display_name", m.get("name", "Unknown")),
                            credit_cost=m.get("credit_cost", 1),
                            max_reference_images=m.get("max_reference_images", 3),
                            max_images_per_request=m.get("max_images_per_request", 4),
                            supported_resolutions=resolutions,
                            supported_aspect_ratios=aspect_ratios,
                        ))
                    logger.info(f"Loaded {len(new_models)} ImageGen models")
                else:
                    new_error = f"Models API returned status={getattr(models_response, 'status_code', '?')}"
                    logger.warning(f"[ImageGen] {new_error}")
            except Exception as e:
                new_error = f"Models fetch failed: {e}"
                logger.error(f"[ImageGen] {new_error}")

            # Fetch styles
            try:
                styles_response = service.get_styles()
                if styles_response.success and styles_response.data:
                    data = styles_response.data
                    if isinstance(data, dict) and "data" in data:
                        data = data["data"]

                    for s in data.get("styles", []):
                        if not s.get("name"):
                            continue
                        new_styles.append(ImageGenStyleInfo(
                            name=s.get("name", ""),
                            display_name=s.get("display_name", s.get("name", "Unknown")),
                            description=s.get("description", ""),
                        ))
                    logger.info(f"Loaded {len(new_styles)} ImageGen styles")
                else:
                    styles_error = f"Styles API returned status={getattr(styles_response, 'status_code', '?')}"
                    new_error = new_error or styles_error
                    logger.warning(f"[ImageGen] {styles_error}")
            except Exception as e:
                styles_error = f"Styles fetch failed: {e}"
                new_error = new_error or styles_error
                logger.error(f"[ImageGen] {styles_error}")

    except Exception as e:
        # Outer catch: import failure or service creation failure
        new_error = str(e)
        logger.error(f"ImageGen cache error: {e}")

    finally:
        if _skipped:
            with _lock:
                _is_loading = False
        else:
            with _lock:
                _cached_models = new_models
                _cached_styles = new_styles
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
        target=_fetch_data_sync, daemon=True, name="MixarImageGenCache"
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
    global _cached_models, _cached_styles, _cache_error, _is_loading, _shutdown_requested
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
        _cached_styles = None
        _cache_error = None
        _is_loading = False
