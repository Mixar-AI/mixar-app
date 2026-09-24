# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reconcile Director beats with the native camera keys they mirror.

A beat is metadata ON a native key column — its still, its timing, its
manifest pose — and the camera's keys are what the dock and the Timeline
both show. Editing keys in the Dope Sheet or Timeline never touches the
``beats``, so without this the two drift apart: a deleted key leaves an
orphaned beat, a key inserted natively (I-key, native auto-keying, pasted
curves) is a pose Director has no beat for, and a key moved in time leaves
its beat — and the still badge the dock draws on it — behind.

A depsgraph handler watches the native Director key frames while directing
(recorded ``JITTER`` samples excluded: they are motion, not beats), and a
debounced timer reconciles, in order:

- **follow** — the frames changed: each key that vanished is paired, in time
  order, with one that appeared, and the beat on it moves there. A grab or
  a scale in any editor keeps time order, so the pairing is the move.
- **prune** — beats still without a key at their frame lose their metadata
  only (``remove_beat(..., delete_keys=False)``): the keys are already gone,
  and a beat's own delete would purge the samples the director kept.
- **adopt** — keys the strip has never seen become beats of the active draft
  shot, mirroring the native timeline's insertion behaviour.
- **repair** — any change to which frames carry keys re-runs the rotation
  continuity filter: natively written keys never pass ``capture_beat``.

Following ``auto_key``: the handler only *detects*, the timer *mutates*,
because editing scene data inside ``depsgraph_update_post`` is unsafe
(re-entrancy / crashes). The timer also waits out a running transform — a
grab passes keys over one another, and the frame set mid-gesture is not the
one the director lets go on — and ``hold`` stands it down while the dock's
own edits keep their beats on their keys themselves.
"""

from __future__ import annotations

import uuid

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

from .anim_curves import camera_key_frames
from .retime import note_beat_timing
from .rotation_curves import repair_rotation_continuity
from .shot_api import active_shot, refresh_manifest, release_preview_range

logger = get_logger(__name__)

_TIMER_INTERVAL = 0.1

_INITIAL_STATE = {
    "key": None,
    "count": None,
    "frames": None,
    # The frames the beats were last reconciled against: what `follow` pairs
    # the current frames with, however many updates a gesture took.
    "synced": None,
    "follow": False,
    "prune": False,
    "adopt": False,
    "repair": False,
}
#: The modal a grab or scale in any animation editor runs as.
_TRANSFORM_MODAL = "TRANSFORM_OT_transform"
_state = dict(_INITIAL_STATE)
#: Set while a dock edit rewrites keys and beats together (`hold`).
_held = False


def _native_key_frames(camera) -> set[int]:
    """Native beat keys, excluding the recorder's dense motion samples."""
    return camera_key_frames(camera, include_samples=False)


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
        # The key went natively; the beat follows it and nothing else.
        if remove_beat(scene, shot, index, delete_keys=False):
            removed += 1
    return removed


def follow_moved_keys(scene, camera, before, after) -> int:
    """Move each beat whose key moved in another editor onto the key.

    *before* and *after* are the native key frames the beats were last
    reconciled against and the ones there are now. Vanished frames pair
    with appeared ones in time order — a grab or a scale keeps order, so the
    pairing IS the move. Anything else (a count that changed with it) is
    left to prune and adopt.
    """
    if not before or not after:
        return 0
    vanished = sorted(set(before) - set(after))
    appeared = sorted(set(after) - set(before))
    if not vanished or len(vanished) != len(appeared):
        return 0
    targets = dict(zip(vanished, appeared))
    moved = 0
    from .native_keys import camera_shots

    for shot in camera_shots(scene, camera):
        followed = [beat for beat in shot.beats if int(beat.frame) in targets]
        for beat in followed:
            beat.frame = targets[int(beat.frame)]
        for beat in sorted(followed, key=lambda item: int(item.frame)):
            note_beat_timing(shot, beat)
        if followed:
            moved += len(followed)
            refresh_manifest(scene, shot)
    return moved


def adopt_native_keyframes(scene, shot) -> int:
    """Create beats for native camera keys the strip has never seen.

    Keys inserted straight into the native timeline (Dope Sheet I-key,
    native auto-keying, pasted F-curves) never pass ``capture_beat``, so
    the camera animated while Director showed no keyframes. Adopted beats
    carry no packed still — only a capture can render one. Frames already
    claimed by any shot directing the same camera stay put: takes and
    split shots deliberately share one camera timeline. The adopted keys
    also never met the rotation continuity filter, so it runs here.
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
        note_beat_timing(shot, beat)
    shot.active_beat_index = len(shot.beats) - 1
    scene.frame_end = max(scene.frame_end, missing[-1])
    repair_rotation_continuity(camera)
    refresh_manifest(scene, shot)
    release_preview_range(scene)
    return len(missing)


def _watchable_shot(scene):
    state = getattr(scene, "mixar_director", None)
    if state is None or not state.is_directing or getattr(state, "recording", False):
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
    if _held:
        return
    shot = _watchable_shot(scene)
    if shot is None:
        _state["key"] = None
        _state["count"] = None
        _state["frames"] = None
        _state["synced"] = None
        return
    # Counts are only comparable while the same camera stays under watch;
    # switching shots resets the baseline instead of faking an edit.
    key = (scene.as_pointer(), shot.camera.name)
    same_camera = _state["key"] == key
    previous = _state["count"] if same_camera else None
    previous_frames = _state["frames"] if same_camera else None
    frames = _native_key_frames(shot.camera)
    count = len(frames)
    _state["key"] = key
    _state["count"] = count
    _state["frames"] = frames
    if previous_frames is None:
        _state["synced"] = frames
    elif frames != previous_frames:
        # Which frames changed is worked out against `synced` when the timer
        # runs, so a gesture spread over many updates pairs as one move.
        _state["follow"] = True
        _ensure_timer()
    # A drop below the beat count is a deletion the timeline hasn't followed.
    if previous is not None and count < previous and count < len(shot.beats):
        _state["prune"] = True
        _ensure_timer()
    # Growth — or a shot freshly under watch — may carry native keys the
    # strip has never seen. An unchanged count is a MOVE and adopts nothing:
    # its beat follows it instead.
    if count and (previous is None or count > previous):
        _state["adopt"] = True
        _ensure_timer()
    # Any change to which frames are keyed — fresh watch, growth, or a MOVE
    # that keeps the count — can reorder the chronological key chain that
    # the rotation continuity filter walks, so it must run again.
    if count and frames != previous_frames:
        _state["repair"] = True
        _ensure_timer()


def _transforming() -> bool:
    """Whether a grab or scale is running in any window."""
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()):
        modal = getattr(window, "modal_operators", None)
        if modal is not None and modal.get(_TRANSFORM_MODAL) is not None:
            return True
    return False


def _sync_timer():
    if _held or _transforming():
        # Keep what was flagged; it is still owed once the gesture lets go.
        return _TIMER_INTERVAL
    follow, prune = _state["follow"], _state["prune"]
    adopt, repair = _state["adopt"], _state["repair"]
    _state["follow"] = _state["prune"] = _state["adopt"] = _state["repair"] = False
    if not (follow or prune or adopt or repair):
        return None
    scene = getattr(bpy.context, "scene", None)
    shot = _watchable_shot(scene) if scene is not None else None
    if shot is None:
        return None
    followed = pruned = adopted = repaired = 0
    try:
        if follow:
            followed = follow_moved_keys(
                scene, shot.camera, _state["synced"], _native_key_frames(shot.camera)
            )
        # After follow: a moved key's beat is on its key again, and only a
        # beat with no key anywhere is an orphan.
        if prune or follow:
            pruned = prune_orphaned_beats(scene, shot)
        if adopt:
            adopted = adopt_native_keyframes(scene, shot)
        if repair:
            repaired = repair_rotation_continuity(shot.camera)
    except Exception:
        logger.exception("Beat sync could not reconcile native keyframes")
        return None
    frames = _native_key_frames(shot.camera)
    _state["count"] = len(frames)
    _state["frames"] = frames
    _state["synced"] = frames
    if followed or pruned or adopted or repaired:
        if followed:
            logger.info("Beat sync moved %s keyframe(s) with their keys", followed)
        if pruned:
            logger.info("Beat sync pruned %s orphaned keyframe(s)", pruned)
        if adopted:
            logger.info("Beat sync adopted %s native keyframe(s)", adopted)
        if repaired:
            logger.info("Beat sync realigned %s rotation key(s)", repaired)
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
    # A fresh baseline: nothing that moved before it is a move to follow.
    _state["synced"] = None
    _state["follow"] = False
    _state["adopt"] = True
    _ensure_timer()


def hold(active: bool) -> None:
    """Stand the watcher down while a dock edit moves keys and beats together.

    A key drag passes moved keys over unselected ones, so mid-drag the native
    key count dips and recovers — a drop the watcher would read as a
    deletion and prune a beat for. The edit keeps its beats on their keys
    itself; letting go re-baselines from whatever it left.
    """
    global _held
    _held = bool(active)
    if not _held:
        request_reconcile()


def register() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update not in handlers:
        handlers.append(_on_depsgraph_update)


def unregister() -> None:
    global _held
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update in handlers:
        handlers.remove(_on_depsgraph_update)
    if bpy.app.timers.is_registered(_sync_timer):
        bpy.app.timers.unregister(_sync_timer)
    _state.update(_INITIAL_STATE)
    _held = False
