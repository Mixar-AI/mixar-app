# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Recording a camera take — what Auto Key does while the timeline plays.

There is ONE switch, and it is Auto Key. Blender has one too, and a director
arriving from Blender knows exactly that one; a second toggle beside it with
the same look invites "which of these do I want?" for a distinction that is
ours, not theirs. So Auto Key answers to what the director is doing:

- **Playing, and something is driving the camera** — the Cinema walk, a
  phone, a transform — key THIS frame, raw. That is a performance, and a
  performance is a curve.
- **Playing, and nothing is driving it** — do nothing. Pressing play to watch
  a shot back is not a request to overwrite it, and this is the whole reason
  the two were briefly separate buttons: without the driver test, a review
  pass flattens the curve it is reviewing.
- **Not playing** — the debounced sparse capture in `core/auto_key.py`: one
  keyframe under the playhead once the camera has been still for a moment.

A recorded frame writes location, rotation and lens and NOTHING else — no
beat, no still, no manifest. A beat renders a PNG to disk
(`_render_viewport_still`), so twenty-four a second is not a throughput
problem, it is the wrong shape. The beats are minted once, when playback
stops, along the curve at the shot's own cadence: the strip, the Speed
slider, Export and the manifest all read beats, and a take with none of them
would leave the surface claiming nothing was recorded.

It keys the FRAME, not the change — a camera that pauses mid-move has to
hold, and a gap in the curve is the camera drifting instead.

It keys from `frame_change_pre`, and that is the whole difference between a
take and a stuck camera. Blender advances the frame, evaluates the camera's
own action and flushes the result back onto the original datablock, and only
THEN runs `frame_change_post`. A recorder reading the camera there reads the
curve it is trying to write: every frame keys the pose the curve already
held, so a whole performance lands as one repeated pose, and the walk's live
matrix is overwritten on every frame boundary — the camera visibly snapping
back to where the curve says it is, twenty-four times a second.

`frame_change_pre` runs after the playhead moves and before any of that, so
the camera still holds the pose the director just flew it to. The key goes
down at the NEW frame, and the evaluation that follows lands on the key we
just wrote — the snap becomes a no-op and the curve records the move.
"""

from __future__ import annotations

from contextlib import contextmanager

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

from ..constants import RECORDED_KEY_TYPE
from .auto_key import move_in_progress
from .frame_math import frames_per_beat
from .keying import key_camera_pose
from .rotation_curves import repair_rotation_continuity
from .shot_api import active_shot

logger = get_logger(__name__)

#: Frames one take may record before it stops itself. At 24fps this is ten
#: minutes — long past any camera move, and short of the runaway a
#: loop-playing scene would otherwise produce.
MAX_RECORDED_FRAMES = 14400

_take = {
    "camera": None,
    "frames": [],
}

#: Re-entrancy guard. `frame_change_pre` fires for EVERY frame change, and
#: Director moves the playhead itself — `_finish` walks the take's beat
#: frames and `capture_beat` parks on the frame it is keying. Those are not
#: the player advancing through a performance, they are the code that keys
#: the performance, and recording them writes the pose the camera is holding
#: right now onto whichever frame it was sent to. Worse, they land AFTER
#: `_finish` has emptied the take, so each one opens a fresh one and leaves
#: the Auto Key chip lit over a take nobody started.
_suspended = {"depth": 0}


@contextmanager
def suspend_recording():
    """Move the playhead without the recorder hearing about it."""
    _suspended["depth"] += 1
    try:
        yield
    finally:
        _suspended["depth"] = max(0, _suspended["depth"] - 1)


def recording_suspended() -> bool:
    return _suspended["depth"] > 0


def _phone_driving() -> bool:
    """A paired phone is flying the camera.

    It pumps poses from a timer rather than a modal, so `move_in_progress`
    cannot see it — and the phone is the recording case a director reaches
    for first.
    """
    window_manager = getattr(getattr(bpy, "context", None), "window_manager", None)
    return bool(getattr(window_manager, "mixar_virtual_camera_connected", False))


def camera_is_being_driven() -> bool:
    """Is a director MOVING the camera right now, rather than watching it?"""
    return move_in_progress() or _phone_driving()


def _playing() -> bool:
    screen = getattr(getattr(bpy, "context", None), "screen", None)
    return bool(getattr(screen, "is_animation_playing", False))


def _armed(scene) -> bool:
    state = getattr(scene, "mixar_director", None)
    return bool(
        state is not None and state.is_directing and state.auto_key
    )


def _key_raw(camera, frame: int) -> None:
    """A take's own keys: the pose and nothing else — no beat, no still.

    The SAME channels a captured beat writes (`core/keying.py`), because the
    beats minted at the end of the take sit on this curve and are retimed
    against it.
    """
    key_camera_pose(camera, frame, keytype=RECORDED_KEY_TYPE)


def _set_recording(scene, value: bool) -> None:
    """Publish whether a take is being laid down, for the Auto Key chip."""
    state = getattr(scene, "mixar_director", None)
    if state is not None and state.recording != value:
        state.recording = value


@persistent
def _on_frame_change(scene, _depsgraph=None) -> None:
    """Key the pose the director has flown the camera to, at the new frame.

    Runs BEFORE the new frame is evaluated (see the module docstring): the
    camera's transform here is the live one, not the one its own curve is
    about to impose.
    """
    if recording_suspended():
        return
    if not _armed(scene) or not _playing() or not camera_is_being_driven():
        return
    shot = active_shot(scene)
    camera = getattr(shot, "camera", None)
    if shot is None or shot.state != 'DRAFT' or camera is None:
        return
    if _take["camera"] is not None and _take["camera"] != camera.name:
        # The shot changed under the take; the frames already recorded belong
        # to the old camera and stay there.
        _finish(scene)
        return
    _take["camera"] = camera.name
    frame = int(scene.frame_current)
    try:
        _key_raw(camera, frame)
    except Exception:
        logger.exception("Recording could not key frame %s", frame)
        return
    _take["frames"].append(frame)
    _set_recording(scene, True)
    if len(_take["frames"]) >= MAX_RECORDED_FRAMES:
        logger.info("Recording stopped at the take length limit")
        _finish(scene)


def _beat_frames(scene, shot, state, frames: list[int]) -> list[int]:
    """The frames of the recorded take that become beats.

    The shot's own beat cadence, so a recorded take reads on the strip the
    way a captured one does — the ends always included, because the first
    and last pose of a move are the two a director will reach for.
    """
    if not frames:
        return []
    first, last = min(frames), max(frames)
    stride = frames_per_beat(
        state.beat_seconds, scene.render.fps, scene.render.fps_base
    )
    wanted = set(range(first, last + 1, max(1, stride))) | {last}
    # Existing beats overwritten by this performance need fresh stills too.
    recorded = set(frames)
    wanted.update(int(beat.frame) for beat in shot.beats if int(beat.frame) in recorded)
    return sorted(wanted)


def _finish(scene) -> None:
    """Playback ended: tidy the curve and mint the take's beats."""
    frames = list(_take["frames"])
    _take["camera"] = None
    _take["frames"] = []
    if not frames:
        _set_recording(scene, False)
        return

    state = getattr(scene, "mixar_director", None)
    shot = active_shot(scene)
    camera = getattr(shot, "camera", None)
    if state is None or shot is None or camera is None:
        _set_recording(scene, False)
        return
    from .capture import capture_beat

    context = bpy.context
    original = int(scene.frame_current)
    minted = 0
    # Every frame_set below is Director's own; none of them is a performance.
    try:
        with suspend_recording():
            repair_rotation_continuity(camera)
            for frame in _beat_frames(scene, shot, state, frames):
                try:
                    scene.frame_set(frame)
                    capture_beat(context, shot, state.beat_seconds, replace_existing=True)
                except Exception:
                    logger.exception("Recording could not mint a beat at frame %s", frame)
                    break
                minted += 1
            scene.frame_set(original)
    finally:
        # Beat sync must remain suspended through the final frame restore.
        _set_recording(scene, False)
    logger.info("Recorded %s frames, minted %s keyframes", len(frames), minted)


@persistent
def _on_playback_end(scene, _depsgraph=None) -> None:
    _finish(scene)


@persistent
def _on_load(_file) -> None:
    _take["camera"] = None
    _take["frames"] = []


_HANDLERS = (
    # PRE, not POST — the pose is only still the director's before the frame
    # is evaluated. See the module docstring.
    ("frame_change_pre", "_on_frame_change"),
    ("animation_playback_post", "_on_playback_end"),
    ("load_post", "_on_load"),
)


def register() -> None:
    for name, callback in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name, None)
        function = globals()[callback]
        if handlers is not None and function not in handlers:
            handlers.append(function)


def unregister() -> None:
    for name, callback in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name, None)
        function = globals()[callback]
        if handlers is not None and function in handlers:
            handlers.remove(function)
    _take["camera"] = None
    _take["frames"] = []
