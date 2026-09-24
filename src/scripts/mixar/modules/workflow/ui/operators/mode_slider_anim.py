# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Redraw pump for the topbar's Zen/Engine slider animation.

The slider's thumb is eased in C++ (`interface_mixar_topbar.cc`), which
needs a stream of frames while it travels. A redraw tag issued from inside
a draw callback does not wake Blender's idle loop, so the painter cannot
drive its own animation — this timer supplies the frames instead, exactly
like the chat's animation pump.

Self-arming: the topbar draw calls `note_mode()` every paint, and a change
since the last paint kicks the pump. Nothing else needs to know about the
animation — in particular the mode operators stay untouched.

Bounded by design: the pump unregisters itself once the travel window has
elapsed, so an idle Mixar never pays for it. If it fails to fire at all,
the easing still lands on the target on the next redraw — the animation is
lost, never the state.
"""

import time

import bpy

_PUMP_INTERVAL = 1.0 / 60.0
"""Frame cadence while the thumb travels."""

_TRAVEL_SECONDS = 0.9
"""Covers the C++ ease (~0.16 s) PLUS the workspace switch it rides through.

A mode change rebuilds the whole screen, which can eat several hundred ms
before the topbar draws again; a short window expired inside that gap and
left the thumb stranded until the next hover."""

_deadline = 0.0
_last_is_zen = None


def _tag_topbars() -> None:
    """Tag every topbar for redraw.

    The topbar is a GLOBAL area — it is not in `screen.areas`, so a normal
    area walk misses it entirely (same gotcha the Director toggle hit).

    `Window.global_areas` is Mixar's own RNA addition (`rna_wm_mixar.cc`)
    and iterates `win->global_areas.areabase` DIRECTLY — it yields the areas
    themselves, so there is no `.areas` on it to walk. Reading one raised
    `AttributeError: bpy_prop_collection: attribute "areas" not found` out of
    the timer on every mode switch. Every other caller in the codebase
    (`updates/ui/topbar_badge.py`, `usage/core/poller.py`,
    `director/ui/properties/director_properties.py`) iterates it directly;
    this is that same shape.
    """
    for window in bpy.context.window_manager.windows:
        for area in getattr(window, "global_areas", None) or ():
            if area.type == 'TOPBAR':
                area.tag_redraw()


def _tick():
    _tag_topbars()
    if time.monotonic() >= _deadline:
        return None
    return _PUMP_INTERVAL


def kick() -> None:
    """Run the pump for one travel window. Idempotent while already running."""
    global _deadline
    was_idle = _deadline <= time.monotonic()
    _deadline = time.monotonic() + _TRAVEL_SECONDS
    if was_idle and not bpy.app.timers.is_registered(_tick):
        try:
            bpy.app.timers.register(_tick, first_interval=0.0)
        except Exception:  # noqa: BLE001 — never let a pump failure break the draw
            pass


_last_flags: dict = {}


def note_flag(key: str, value) -> None:
    """Kick the pump when \a value changed since the last paint.

    Generic counterpart to `note_mode` for any other animated topbar state
    (the Cinema Mode switch knob). First sighting only records.
    """
    previous = _last_flags.get(key, None)
    _last_flags[key] = value
    if previous is not None and previous != value:
        kick()


def note_mode(is_zen: bool) -> None:
    """Record the mode the topbar just drew; kick the pump when it changed."""
    global _last_is_zen
    if _last_is_zen is None:
        _last_is_zen = is_zen
        return
    if is_zen != _last_is_zen:
        _last_is_zen = is_zen
        kick()


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)


classes = ()
