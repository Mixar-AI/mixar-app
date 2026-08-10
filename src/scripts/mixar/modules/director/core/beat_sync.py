# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Prune Director beats whose native camera keys were deleted elsewhere.

The timeline strip and its orange handles are drawn from the ``beats``
collection, but a keyframe's actual pose lives in native camera F-curves.
Deleting keys in the Dope Sheet or Timeline editor removes the F-curve keys
without touching the ``beats``, so the orange handles linger and the manifest
still references poses that no longer exist.

A depsgraph handler watches the native Director key count while directing and,
when it drops below the beat count (a genuine deletion — never a move, which
keeps the count), a debounced timer prunes the orphaned beats through the
ordinary ``remove_beat`` path. Following ``auto_key``: the handler only
*detects*, the timer *mutates*, because editing scene data inside
``depsgraph_update_post`` is unsafe (re-entrancy / crashes).
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

from .anim_curves import assigned_fcurves
from .shot_api import active_shot

logger = get_logger(__name__)

_TIMER_INTERVAL = 0.1

_CAMERA_PATHS = {
    "location",
    "rotation_euler",
    "rotation_quaternion",
    "rotation_axis_angle",
}

_state = {"count": None, "dirty": False}


def _native_key_frames(camera) -> set[int]:
    """Every integer frame carrying a native Director camera key."""
    frames: set[int] = set()
    if camera is None:
        return frames
    for fcurve in assigned_fcurves(camera):
        if fcurve.data_path in _CAMERA_PATHS:
            for point in fcurve.keyframe_points:
                frames.add(round(float(point.co[0])))
    data = getattr(camera, "data", None)
    if data is not None:
        for fcurve in assigned_fcurves(data):
            if fcurve.data_path == "lens":
                for point in fcurve.keyframe_points:
                    frames.add(round(float(point.co[0])))
    return frames


def prune_orphaned_beats(scene, shot) -> int:
    """Remove beats with no native camera key at their frame.

    Only prunes on a genuine deletion (fewer native key frames than beats).
    Equal counts with shifted frames means a key was MOVED in the Dope Sheet,
    not deleted, so a beat and its packed still are never destroyed on a move.
    """
    camera = getattr(shot, "camera", None)
    if camera is None or not shot.beats:
        return 0
    native = _native_key_frames(camera)
    if len(native) >= len(shot.beats):
        return 0
    orphans = [
        index
        for index, beat in enumerate(shot.beats)
        if round(int(beat.frame)) not in native
    ]
    if not orphans:
        return 0

    from .capture import remove_beat

    removed = 0
    for index in sorted(orphans, reverse=True):
        if remove_beat(scene, shot, index):
            removed += 1
    return removed


def _watchable_shot(scene):
    state = getattr(scene, "mixar_director", None)
    if state is None or not state.is_directing:
        return None
    shot = active_shot(scene)
    if shot is None or shot.state != 'DRAFT' or shot.camera is None:
        return None
    return shot


def _redraw() -> None:
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()):
            if area.type in {'VIEW_3D', 'MIXIE'}:
                area.tag_redraw()


@persistent
def _on_depsgraph_update(scene, _depsgraph) -> None:
    shot = _watchable_shot(scene)
    if shot is None:
        _state["count"] = None
        return
    count = len(_native_key_frames(shot.camera))
    previous = _state["count"]
    _state["count"] = count
    # A drop below the beat count is a deletion the timeline hasn't followed.
    if previous is not None and count < previous and count < len(shot.beats):
        _state["dirty"] = True
        _ensure_timer()


def _prune_timer():
    if not _state["dirty"]:
        return None
    _state["dirty"] = False
    scene = getattr(bpy.context, "scene", None)
    shot = _watchable_shot(scene) if scene is not None else None
    if shot is None:
        return None
    try:
        removed = prune_orphaned_beats(scene, shot)
    except Exception:
        logger.exception("Beat sync could not prune orphaned keyframes")
        return None
    if removed:
        logger.info("Beat sync pruned %s orphaned keyframe(s)", removed)
        _state["count"] = len(_native_key_frames(shot.camera))
        _redraw()
    return None


def _ensure_timer() -> None:
    if not bpy.app.timers.is_registered(_prune_timer):
        bpy.app.timers.register(_prune_timer, first_interval=_TIMER_INTERVAL)


def register() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update not in handlers:
        handlers.append(_on_depsgraph_update)


def unregister() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update in handlers:
        handlers.remove(_on_depsgraph_update)
    if bpy.app.timers.is_registered(_prune_timer):
        bpy.app.timers.unregister(_prune_timer)
    _state.update({"count": None, "dirty": False})
