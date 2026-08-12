# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalog-driven labels for the moodboard sidebar capability tabs.

Blender consumes a Panel's ``bl_label``/``bl_category`` once at class
registration (there is no draw-time callback for tab names), so dynamic
tab labels work in two stages:

1. ``apply_catalog_labels()`` — run by ``moodboard_sidebar_panels`` at
   module load, before its classes register. The bootstrap loads the
   persisted catalog payload synchronously before the deferred UI batch
   imports the panels, so an authenticated user sees current DB labels
   from the first draw; offline / pre-auth the hardcoded fallbacks stand.
2. ``refresh_tab_labels()`` — invoked from the catalog cache's
   main-thread swap callback after a revalidation lands a new payload;
   it unregisters and re-registers ONLY the panels whose label changed
   (rare, so losing that panel's expand state is acceptable).

``bl_idname``s are never touched — other code (tour driver, force-open
tricks) keys on them. Code that switches the sidebar via
``region.active_panel_category`` must resolve capability tabs through
``get_tab_category()`` instead of literal label strings.

The capability→panel mapping is registered by ``moodboard_sidebar_panels``
via ``init_capability_tabs()`` (kept there, next to the classes, to avoid
a circular import).
"""

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE

logger = get_logger(__name__)

# capability key -> (panel class, offline fallback label). Populated by
# moodboard_sidebar_panels.init at its import; empty until then.
_capability_tabs = {}

# Re-entrancy guard for refresh_tab_labels().
_refresh_in_progress = False


def init_capability_tabs(mapping):
    """Register the capability→(panel class, fallback label) mapping."""
    _capability_tabs.clear()
    _capability_tabs.update(mapping)


def _resolve_label(capability_key, fallback):
    """Current catalog label for a capability, or *fallback* offline."""
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_capability_label,
        )
        return get_capability_label(capability_key, fallback)
    except Exception:
        return fallback


def get_tab_category(capability_key, fallback=""):
    """Current sidebar category string for a capability's tab.

    Reads the panel class's live ``bl_category`` (what Blender actually
    registered) so ``region.active_panel_category`` switching keeps
    finding the tab across catalog label renames. Returns *fallback* for
    unknown keys. Never raises.
    """
    entry = _capability_tabs.get(capability_key)
    if entry is None:
        return fallback
    cls, default = entry
    try:
        return getattr(cls, 'bl_category', None) or default
    except Exception:
        return default


def apply_catalog_labels():
    """Resolve every capability panel's label/category from the catalog.

    Called by ``moodboard_sidebar_panels`` at module load, before its
    ``classes`` tuple is auto-registered.
    """
    for capability_key, (cls, fallback) in _capability_tabs.items():
        label = _resolve_label(capability_key, fallback)
        cls.bl_label = label
        cls.bl_category = label


def refresh_tab_labels():
    """Re-register only the capability panels whose label changed.

    Called from ``generation_catalog_cache._on_catalog_swapped`` — a
    main-thread ``bpy.app.timers`` callback — after a revalidation swaps
    in a new payload (bpy class registration must never run off the main
    thread). No-op when nothing changed, re-entrantly, or when the MIXIE
    space (and therefore these panels) is unavailable; panels that were
    never registered (mid-batch load, logout teardown) only get their
    class attributes updated. Never raises.
    """
    global _refresh_in_progress
    if _refresh_in_progress or not MIXIE_SPACE_AVAILABLE or not _capability_tabs:
        return
    _refresh_in_progress = True
    try:
        import bpy

        relabelled = False
        for capability_key, (cls, fallback) in _capability_tabs.items():
            label = _resolve_label(capability_key, fallback)
            if label == getattr(cls, 'bl_category', None):
                continue
            was_registered = getattr(cls, 'is_registered', False)
            try:
                if was_registered:
                    bpy.utils.unregister_class(cls)
                cls.bl_label = label
                cls.bl_category = label
                if was_registered:
                    bpy.utils.register_class(cls)
                    relabelled = True
                logger.info(
                    "Moodboard tab relabelled: %s -> %r", cls.__name__, label,
                )
            except Exception:
                logger.exception(
                    "Failed to relabel moodboard tab %s", cls.__name__
                )
        if relabelled:
            try:
                from mixar.modules.common.utils.platform_utils import (
                    trigger_ui_redraw,
                )
                trigger_ui_redraw()
            except Exception:
                pass
    except Exception:
        logger.exception("refresh_tab_labels failed")
    finally:
        _refresh_in_progress = False
