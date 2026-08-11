# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reconcile Director beats with the native camera keys they mirror.

The timeline strip and its orange handles are drawn from the ``beats``
collection, but a keyframe's actual pose lives in native camera F-curves.
Editing those keys in the Dope Sheet or Timeline editor never touches the
``beats``, so the strip can drift from the animation in both directions:
deleted keys leave orphaned handles and stale manifest poses, while keys
inserted natively (I-key, native auto-keying, pasted curves) animate the
camera through a strip that shows nothing.

A depsgraph handler watches the native Director key count while directing.
A drop below the beat count (a genuine deletion — never a move, which keeps
the count) prunes orphaned beats through the ordinary ``remove_beat`` path;
growth — or a shot freshly under watch — adopts keys the strip has never
seen as beats of the active draft shot, mirroring the native timeline's
insertion behavior. Following ``auto_key``: the handler only *detects*, the
debounced timer *mutates*, because editing scene data inside
``depsgraph_update_post`` is unsafe (re-entrancy / crashes).
"""

from __future__ import annotations

import uuid

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

from .anim_curves import assigned_fcurves
from .shot_api import active_shot, refresh_manifest, scope_preview_range

logger = get_logger(__name__)

_TIMER_INTERVAL = 0.1

_CAMERA_PATHS = {
    "location",
    "rotation_euler",
    "rotation_quaternion",
    "rotation_axis_angle",
}

_state = {"key": None, "count": None, "prune": False, "adopt": False}


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


def adopt_native_keyframes(scene, shot) -> int:
    """Create beats for native camera keys the strip has never seen.

    Keys inserted straight into the native timeline (Dope Sheet I-key,
    native auto-keying, pasted F-curves) never pass ``capture_beat``, so
    the camera animated while Director showed no keyframes. Adopted beats
    carry no packed still — only a capture can render one. Frames already
    claimed by any shot directing the same camera stay put: takes and
    split shots deliberately share one camera timeline.
    """
    camera = getattr(shot, "camera", None)
    if camera is None or shot.state != 'DRAFT':
        return 0
    native = _native_key_frames(camera)
    if not native:
        return 0
    state = getattr(scene, "mixar_director", None)
    shots = state.shots if state is not None else (shot,)
    covered = {
        int(beat.frame)
        for item in shots
        if item.camera == camera
        for beat in item.beats
    }
    missing = sorted(native - covered)
    if not missing:
        return 0
    for frame in missing:
        beat = shot.beats.add()
        beat.beat_id = uuid.uuid4().hex
        beat.frame = frame
    shot.active_beat_index = len(shot.beats) - 1
    scene.frame_end = max(scene.frame_end, missing[-1])
    refresh_manifest(scene, shot)
    scope_preview_range(scene, shot)
    return len(missing)


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
        _state["key"] = None
        _state["count"] = None
        return
    # Counts are only comparable while the same camera stays under watch;
    # switching shots resets the baseline instead of faking an edit.
    key = (scene.as_pointer(), shot.camera.name)
    previous = _state["count"] if _state["key"] == key else None
    count = len(_native_key_frames(shot.camera))
    _state["key"] = key
    _state["count"] = count
    # A drop below the beat count is a deletion the timeline hasn't followed.
    if previous is not None and count < previous and count < len(shot.beats):
        _state["prune"] = True
        _ensure_timer()
    # Growth — or a shot freshly under watch — may carry native keys the
    # strip has never seen. An unchanged count is a MOVE and adopts nothing:
    # the moved key's beat still exists, only its frame went stale.
    if count and (previous is None or count > previous):
        _state["adopt"] = True
        _ensure_timer()


def _sync_timer():
    prune, adopt = _state["prune"], _state["adopt"]
    _state["prune"] = _state["adopt"] = False
    if not (prune or adopt):
        return None
    scene = getattr(bpy.context, "scene", None)
    shot = _watchable_shot(scene) if scene is not None else None
    if shot is None:
        return None
    pruned = adopted = 0
    try:
        if prune:
            pruned = prune_orphaned_beats(scene, shot)
        if adopt:
            adopted = adopt_native_keyframes(scene, shot)
    except Exception:
        logger.exception("Beat sync could not reconcile native keyframes")
        return None
    if pruned or adopted:
        if pruned:
            logger.info("Beat sync pruned %s orphaned keyframe(s)", pruned)
        if adopted:
            logger.info("Beat sync adopted %s native keyframe(s)", adopted)
        _state["count"] = len(_native_key_frames(shot.camera))
        _redraw()
    return None


def _ensure_timer() -> None:
    if not bpy.app.timers.is_registered(_sync_timer):
        bpy.app.timers.register(_sync_timer, first_interval=_TIMER_INTERVAL)


def request_reconcile() -> None:
    """Reconcile now instead of waiting for the next depsgraph event.

    The watcher only ticks inside ``depsgraph_update_post``, but entering
    Director or switching shots changes which camera is under watch without
    causing a depsgraph update — an already-keyed camera showed an empty
    strip until some unrelated edit (an outliner rename) happened to tick
    the handler. Resets the baseline and runs the adopt pass immediately;
    the timer still gates on an active directing session.
    """
    _state["key"] = None
    _state["adopt"] = True
    _ensure_timer()


def register() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update not in handlers:
        handlers.append(_on_depsgraph_update)


def unregister() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update in handlers:
        handlers.remove(_on_depsgraph_update)
    if bpy.app.timers.is_registered(_sync_timer):
        bpy.app.timers.unregister(_sync_timer)
    _state.update({"key": None, "count": None, "prune": False, "adopt": False})
