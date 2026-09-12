# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sliding moodboard drawer state and clock.

Three WindowManager properties shared with the C++ drawer
(``editors/space_view3d/view3d_moodboard_drawer.cc``):

  - mixar_moodboard_drawer_amount: how far the Zen Mode drawer is pulled out,
    0 (shut) .. 1 (open). C reads it on every draw, and writes it on every
    frame of a grip drag.
  - mixar_moodboard_drawer_target: the side the drawer settles on, 0 or 1.
    Written by the grip (a click flips the current target, a release after a
    drag keeps the chosen width or closes a small pull) and by ``view3d.moodboard_drawer_{toggle,set}``.

  - mixar_moodboard_drawer_width: chosen width in UI units, remembered when
    closing and reopening. Grip travel can fill the available viewport.

C owns the wall-clock ease (``display_amount``, ease-out cubic over
``VIEW3D_MOODBOARD_DRAWER_SLIDE_SECONDS``) and a ``TIMERNOTIFIER`` that
tags only the drawer region. This module's 60 Hz clock calls
``view3d.moodboard_drawer_update`` so RNA meets the target; the C timer
is what paints the in-between frames, because the idle interval here is
0.1 s and waiting on it was the first-frame jump.

All properties are SKIP_SAVE: a half-open drawer is a gesture in progress,
never saved scene data.
"""

import bpy
from bpy.props import FloatProperty, IntProperty

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_PROP_NAMES = (
    'mixar_moodboard_drawer_amount',
    'mixar_moodboard_drawer_target',
    'mixar_moodboard_drawer_width',
)

# 60 Hz while the drawer is moving, and a slow poll the rest of the time. The
# tick has to stay registered to be able to notice a grip release, so the idle
# interval is what the drawer costs a session that never opens it: two property
# reads, ten times a second.
_ANIMATION_INTERVAL = 1.0 / 60.0
_IDLE_INTERVAL = 0.1


def _view3d_override():
    """Window/area/region into which the update operator can be called.

    A timer has no area of its own, and the operator's poll needs a 3D View in
    the Zen Mode workspace, so the context is assembled by hand rather than
    inherited. Returns None when no 3D View is on screen yet.
    """
    window_manager = getattr(bpy.context, 'window_manager', None)
    if window_manager is None:
        return None

    for window in window_manager.windows:
        if window.workspace.name != 'Zen Mode':
            continue
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            return {
                'window': window,
                'screen': screen,
                'area': area,
                'region': region,
                'space_data': area.spaces.active,
            }
    return None


def _drawer_tick():
    """Advance a drawer on its way to its target, and schedule the next step."""
    window_manager = getattr(bpy.context, 'window_manager', None)
    if window_manager is None:
        return _IDLE_INTERVAL

    amount = float(window_manager.mixar_moodboard_drawer_amount)
    target = float(window_manager.mixar_moodboard_drawer_target)
    if amount == target:
        return _IDLE_INTERVAL

    override = _view3d_override()
    if override is None:
        return _IDLE_INTERVAL

    try:
        with bpy.context.temp_override(**override):
            bpy.ops.view3d.moodboard_drawer_update()
    except Exception as error:
        # No 3D View that will answer the operator — the user left Zen Mode
        # mid-slide, or the screens are still coming up. Settle on the target
        # instead of chasing one nothing can reach, so the timer goes quiet.
        logger.debug("Moodboard drawer update unavailable: %s", error)
        window_manager.mixar_moodboard_drawer_amount = float(target)
        return _IDLE_INTERVAL

    return _ANIMATION_INTERVAL


def register():
    bpy.types.WindowManager.mixar_moodboard_drawer_amount = FloatProperty(
        name="Moodboard Drawer",
        description="How far the Zen Mode moodboard drawer is pulled out, "
                    "0 shut and 1 open",
        default=0.0,
        min=0.0,
        max=1.0,
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixar_moodboard_drawer_target = IntProperty(
        name="Moodboard Drawer Target",
        description="Side the Zen Mode moodboard drawer settles on, "
                    "0 shut and 1 open",
        default=0,
        min=0,
        max=1,
        options={'SKIP_SAVE'},
    )

    bpy.types.WindowManager.mixar_moodboard_drawer_width = FloatProperty(
        name="Moodboard Drawer Width",
        description="Width chosen by dragging the moodboard grip",
        default=340.0,
        min=120.0,
        max=100000.0,
        options={'SKIP_SAVE'},
    )

    if not bpy.app.timers.is_registered(_drawer_tick):
        # Persistent: the properties are SKIP_SAVE, so a file load resets the
        # drawer to shut and this timer has to outlive the load to keep
        # settling it afterwards.
        bpy.app.timers.register(
            _drawer_tick, first_interval=_IDLE_INTERVAL, persistent=True
        )


def unregister():
    if bpy.app.timers.is_registered(_drawer_tick):
        bpy.app.timers.unregister(_drawer_tick)
    for name in _PROP_NAMES:
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
