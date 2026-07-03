# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Sidebar Animation Manager

Timer-driven animation for the generative panel expand/collapse.
The animation progress (0.0–1.0) is stored on WindowManager so it
is session-only (not saved to .blend) and accessible from any context.
"""

import bpy
from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.mixie_space_utils import redraw_mixie_areas

logger = get_logger(__name__)

# Animation constants
_ANIM_SPEED = 0.14      # Progress delta per tick (0-1 range)
_ANIM_INTERVAL = 0.016  # ~60 fps tick rate

# Module-level guard to prevent duplicate timer registration
_anim_running = False


def _anim_tick():
    """Timer callback: advance expand_anim toward its target each tick."""
    global _anim_running
    try:
        wm = bpy.context.window_manager
        if not hasattr(wm, 'mixie_sidebar_expand_anim'):
            _anim_running = False
            return None

        target = 1.0 if getattr(wm, 'mixie_sidebar_is_expanded', False) else 0.0
        current = wm.mixie_sidebar_expand_anim
        delta = target - current

        if abs(delta) <= _ANIM_SPEED:
            wm.mixie_sidebar_expand_anim = target
            redraw_mixie_areas()
            _anim_running = False
            return None  # Stop timer

        wm.mixie_sidebar_expand_anim = current + (_ANIM_SPEED if delta > 0 else -_ANIM_SPEED)
        redraw_mixie_areas()
        return _ANIM_INTERVAL

    except Exception as e:
        logger.debug("Sidebar anim tick error: %s", e)
        _anim_running = False
        return None


def _ensure_timer_running() -> None:
    """Must be called from the main thread only. _timer_running is not lock-protected."""
    global _anim_running
    if _anim_running or bpy.app.timers.is_registered(_anim_tick):
        return
    _anim_running = True
    bpy.app.timers.register(_anim_tick, first_interval=_ANIM_INTERVAL)


def expand_panel() -> None:
    """Animate the generative panel to the fully expanded state."""
    try:
        wm = bpy.context.window_manager
        if hasattr(wm, 'mixie_sidebar_is_expanded'):
            wm.mixie_sidebar_is_expanded = True
        _ensure_timer_running()
    except Exception as e:
        logger.debug("expand_panel error: %s", e)


def collapse_panel() -> None:
    """Animate the generative panel to the fully collapsed state."""
    try:
        wm = bpy.context.window_manager
        if hasattr(wm, 'mixie_sidebar_is_expanded'):
            wm.mixie_sidebar_is_expanded = False
        _ensure_timer_running()
    except Exception as e:
        logger.debug("collapse_panel error: %s", e)


def toggle_panel(tab_id: str) -> None:
    """
    Toggle the sidebar panel for the given tab.

    Clicking the same tab while expanded collapses. Clicking a different tab
    (or clicking while collapsed) switches to that tab and expands.
    """
    try:
        wm = bpy.context.window_manager
        scene = bpy.context.scene
        sidebar = getattr(scene, 'mixie_moodboard_sidebar', None)
        if not sidebar:
            return

        # Remap retired tabs into their new parent + subtab
        subtab_attr = None   # sidebar property name for the subtab
        subtab_value = None  # value to set

        if tab_id == 'LOOKDEV':
            tab_id = 'BLOCKOUT_TO_RENDER'
        elif tab_id == 'HUNYUAN':
            tab_id = 'IMAGE_TO_3D'
            subtab_attr = 'image_to_3d_subtab'
            subtab_value = 'PRO'
        elif tab_id in ('SEGMENT_TO_3D', 'PART_SEGMENT', 'MESH_SEGMENT'):
            subtab_attr = 'segmentation_subtab'
            subtab_value = 'SEGMENT_TO_3D' if tab_id == 'SEGMENT_TO_3D' else 'PART_SEGMENT'
            tab_id = 'SEGMENTATION'

        is_expanded = getattr(wm, 'mixie_sidebar_is_expanded', False)
        current_tab = sidebar.active_tab

        if is_expanded and current_tab == tab_id:
            # If a subtab override is requested, switch subtab instead of collapsing
            if subtab_attr and getattr(sidebar, subtab_attr) != subtab_value:
                setattr(sidebar, subtab_attr, subtab_value)
            else:
                collapse_panel()
        else:
            sidebar.active_tab = tab_id
            if subtab_attr:
                setattr(sidebar, subtab_attr, subtab_value)
            expand_panel()

    except Exception as e:
        logger.debug("toggle_panel error: %s", e)
