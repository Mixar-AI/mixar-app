# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded, main-thread redraw animation for the global sound toggle."""

import time

import bpy

from ..constants import SOUND_FEEDBACK_TIMING

_started = None


def expansion(now=None, *, reduce_motion=False):
    """Read the current expansion without starting timers or changing UI state."""
    if _started is None:
        return 0.0
    elapsed = (time.monotonic() if now is None else now) - _started
    grow, hold, shrink = SOUND_FEEDBACK_TIMING
    if elapsed < 0 or elapsed >= grow + hold + shrink:
        return 0.0
    if reduce_motion:
        return 1.0
    if elapsed < grow:
        fraction = elapsed / grow
    elif elapsed < grow + hold:
        return 1.0
    else:
        fraction = 1.0 - (elapsed - grow - hold) / shrink
    return fraction * fraction * (3.0 - 2.0 * fraction)


def redraw():
    # Topbars are global areas, outside screen.areas. Include Preferences so
    # both entry points immediately reflect the same persisted preference.
    for window in bpy.context.window_manager.windows:
        for area in list(window.screen.areas) + list(getattr(window, 'global_areas', ())):
            if area.type in {'TOPBAR', 'PREFERENCES'}:
                area.tag_redraw()


def _tick():
    global _started
    if _started is None:
        return None
    if time.monotonic() - _started >= sum(SOUND_FEEDBACK_TIMING):
        _started = None
        redraw()
        return None
    redraw()
    return 1.0 / 60.0


def show():
    global _started
    _started = time.monotonic()
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.0)
    redraw()


def cancel():
    global _started
    _started = None
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    redraw()
