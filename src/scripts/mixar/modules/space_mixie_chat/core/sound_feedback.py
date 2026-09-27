# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded, main-thread redraw animation for the global sound toggle."""

import time

import bpy

from ..constants import SOUND_FEEDBACK_TIMING

_started = None
# Captured by show(): the tween-free path redraws only at the hold's edges.
_reduce_motion = False


def expansion(now=None, *, reduce_motion=None):
    """Read the current expansion without starting timers or changing UI state."""
    if _started is None:
        return 0.0
    if reduce_motion is None:
        reduce_motion = _reduce_motion
    elapsed = (time.monotonic() if now is None else now) - _started
    grow, hold, shrink = SOUND_FEEDBACK_TIMING
    if elapsed < 0 or elapsed >= grow + hold + shrink:
        return 0.0
    if reduce_motion:
        # No tween: the label is simply shown for the hold.
        return 1.0 if grow <= elapsed < grow + hold else 0.0
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
    elapsed = time.monotonic() - _started
    grow, hold, shrink = SOUND_FEEDBACK_TIMING
    end = grow + hold if _reduce_motion else grow + hold + shrink
    if elapsed >= end:
        _started = None
        redraw()
        return None
    redraw()
    if not _reduce_motion:
        return 1.0 / 60.0
    # Tween-free: nothing changes between the hold's edges, so sleep until the next one.
    return max(0.0, (grow if elapsed < grow else end) - elapsed)


def show(*, reduce_motion=False):
    global _started, _reduce_motion
    _started = time.monotonic()
    _reduce_motion = bool(reduce_motion)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.0)
    redraw()


def cancel():
    global _started
    _started = None
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    redraw()
