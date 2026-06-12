# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Grid redraw pump.

Agent scripts mutate scenes that are not the window's active scene (per-scene
sessions execute against their own scene), which emits no notifiers the Scene
Grid's C++ listener can react to. This timer keeps SCENE_GRID areas redrawing
while any scene has a busy agent; the C++ draw pass self-dirties busy tiles
and rate-limits actual re-renders, so redundant ticks are cheap.

Mirrors redraw_chat_areas() in space_mixie_chat/core/ui_utils.py.
"""

import bpy

from ..constants import PUMP_INTERVAL_BUSY, PUMP_INTERVAL_IDLE


def _any_scene_busy():
    return any(
        getattr(scene, 'mixie_chat_is_busy', False) for scene in bpy.data.scenes
    )


def _redraw_scene_grid_areas():
    wm = getattr(bpy.context, 'window_manager', None)
    if not wm:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'SCENE_GRID':
                area.tag_redraw()


def _pump():
    try:
        if _any_scene_busy():
            _redraw_scene_grid_areas()
            return PUMP_INTERVAL_BUSY
        return PUMP_INTERVAL_IDLE
    except Exception:
        # Context can be briefly unavailable (file load, render); keep ticking.
        return PUMP_INTERVAL_IDLE


def register():
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=PUMP_INTERVAL_IDLE, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)
