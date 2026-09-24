# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Debounced automatic keyframe capture for camera edits.

A move needs a BOUNDARY before it can be keyed, and most ways of moving a
camera have none: a gizmo drag, a WASD nudge and a click on the aerial map all
just stream depsgraph updates. So a handler marks the camera dirty and a timer
captures once the camera has been still for ``DEBOUNCE_SECONDS``.

This used to run in Precise mode ALONE, which is the one mode the Cinema
surface never puts a director in — the surface's own ways of moving a camera
are the nudge and the aerial placement, so Auto Key was on and did nothing.
It now watches every mode except the two that must not key:

- EXPLORE parks the shot camera and flies a free view; there is no camera
  motion to key, and the pose that exists is stale.
- A running walk is owned by the walk supervisor
  (``MIXAR_OT_director_navigate``), which captures ONCE on exit because it
  knows exactly when the move ended. Debouncing underneath it would litter the
  walk with keys every time the director paused to look.

A frame change rebaselines instead of dirtying: scrubbing or playback moves the
camera through its animation, and capturing those poses would duplicate keys
the user never authored.

Three of Blender's own auto-key rules it keeps (``_DEFER_MODALS``,
``_playing``, the ``baseline``):

- **Key at the END of a move.** Blender auto-keys when a transform confirms;
  the debounce is this module's stand-in for a boundary the other movers do
  not have, so where a real boundary EXISTS it defers to it — a running
  transform or walk is a move that has not finished. Deferring holds the
  capture back; it never stops the watcher tracking, because a confirm moves
  the camera no further than the last modal step already did.
- **Only insert needed** (``AUTOKEY_FLAG_INSERTNEEDED``). The pose the frame
  was rebaselined at is remembered, so a camera nudged away and back to where
  it started settles on something already keyed and is left alone.
- **Never during playback.** Not because Blender refuses to — it keys
  wherever the playhead reached when a transform confirms — but because a
  beat costs a `frame_set` and a still rendered to disk, which is the wrong
  shape entirely under a running playhead. Flying the camera live while the
  timeline plays is `core/record.py`, which writes raw keys and no beats.

The one rule it cannot keep is the boundary itself: a move abandoned by a
frame change inside the debounce window is not keyed, because the pose it
would key no longer exists — the animation has already moved the camera on.
"""

from __future__ import annotations

import time

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

from .shot_api import active_shot

logger = get_logger(__name__)

DEBOUNCE_SECONDS = 0.8
_TIMER_INTERVAL = 0.25

_watch = {
    "key": None,
    "frame": None,
    "sig": None,
    # The pose this frame was rebaselined at — what the shot's animation
    # already holds here. A move that settles back on it needs no key, which
    # is Blender's "only insert needed".
    "baseline": None,
    "dirty": False,
    "changed_at": 0.0,
    "captured_sig": None,
}


def camera_signature(camera) -> tuple:
    """A rounded pose fingerprint: world transform plus focal length."""
    matrix = camera.matrix_world
    values = [round(matrix[row][col], 5) for row in range(4) for col in range(4)]
    values.append(round(float(camera.data.lens), 3))
    return tuple(values)


def mark_captured(shot) -> None:
    """Record the current pose as captured so the watcher won't re-key it."""
    camera = getattr(shot, "camera", None)
    if camera is not None:
        _watch["captured_sig"] = camera_signature(camera)


def _reset(key=None, frame=None, sig=None) -> None:
    _watch.update(
        {"key": key, "frame": frame, "sig": sig, "baseline": sig, "dirty": False}
    )


#: Modal operators that mean "not yet".
#:
#: The WALKS key for themselves: `MIXAR_OT_director_navigate` supervises the
#: Cinema walk and captures ONCE on exit, because it knows exactly when the
#: move ended. Naming only `VIEW3D_OT_walk` stopped being enough the moment
#: Cinema Mode grew its own walk, so the debounce ran underneath the one walk
#: a director actually uses and keyed every pause.
#:
#: A running TRANSFORM is a move that has not finished. Blender auto-keys when
#: the transform CONFIRMS; a debounce that fires mid-drag — the director holds
#: still for a moment while lining a shot up — keys a pose nobody chose and
#: then keys the real one over it.
_DEFER_MODALS = (
    "MIXAR_OT_director_walk",
    "VIEW3D_OT_walk",
    "TRANSFORM_OT_translate",
    "TRANSFORM_OT_rotate",
    "TRANSFORM_OT_resize",
    "TRANSFORM_OT_transform",
)


def move_in_progress() -> bool:
    """Whether a modal that owns this move is still running.

    Public because `core/record.py` asks the SAME question for the opposite
    answer: a driver on the camera means "not yet" to the debounce and
    "record this frame" to a take. One question, one list, one home.
    """
    window = getattr(getattr(bpy, "context", None), "window", None)
    modal_operators = getattr(window, "modal_operators", None)
    if modal_operators is None:
        return False
    try:
        return any(modal_operators.get(name) is not None for name in _DEFER_MODALS)
    except (AttributeError, ReferenceError, TypeError):
        return False


def _playing() -> bool:
    """Whether the animation is running.

    NOT because Blender refuses to auto-key during playback — it does not, it
    keys wherever the playhead has reached when a transform confirms. It is
    because CAPTURING is the wrong thing to do here: `capture_beat` calls
    `scene.frame_set` and renders a still to disk, neither of which belongs
    under a running playhead.

    Recording a camera live while the timeline plays is a real and wanted
    act, and it is `core/record.py` — raw keys, one per frame, no beat and no
    still. Auto Key is the other half: a camera that STOPS.
    """
    screen = getattr(getattr(bpy, "context", None), "screen", None)
    return bool(getattr(screen, "is_animation_playing", False))


def _deferring() -> bool:
    """A modal owns this move, or the animation is running.

    NOT the same question as `_watchable_shot`: this one means "not yet",
    where that one means "nothing to watch". Only the CAPTURE waits on it —
    the watcher keeps tracking right through, because a transform's confirm
    moves the camera no further than its last modal step did and so streams
    no new depsgraph update. A deferral that stopped tracking, or that threw
    the pending move away, would lose the keyframe outright: drag the camera,
    hold still long enough for one debounce tick, let go, nothing keyed.
    """
    return move_in_progress() or _playing()


def _watchable_shot(scene):
    state = getattr(scene, "mixar_director", None)
    if (
        state is None
        or not state.is_directing
        or not state.auto_key
        # EXPLORE parks the shot camera and flies a free view: there is no
        # camera motion to key, and the pose that exists is stale.
        or state.navigation_mode == 'EXPLORE'
    ):
        return None, None
    shot = active_shot(scene)
    if shot is None or shot.state != 'DRAFT' or shot.camera is None:
        return None, None
    return state, shot


@persistent
def _on_depsgraph_update(scene, _depsgraph) -> None:
    from .record import recording_suspended

    if recording_suspended():
        return
    state, shot = _watchable_shot(scene)
    if state is None:
        _reset()
        return
    key = (scene.as_pointer(), shot.camera.name)
    sig = camera_signature(shot.camera)
    frame = int(scene.frame_current)
    if _watch["key"] != key or _watch["frame"] != frame:
        _reset(key=key, frame=frame, sig=sig)
        return
    if sig != _watch["sig"]:
        _watch.update({"sig": sig, "dirty": True, "changed_at": time.monotonic()})
        _ensure_timer()


def _debounce_timer():
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return _TIMER_INTERVAL
    state, shot = _watchable_shot(scene)
    if state is None:
        _watch["dirty"] = False
        directing = getattr(scene, "mixar_director", None)
        keep_alive = bool(
            directing and directing.is_directing and directing.auto_key
        )
        return _TIMER_INTERVAL if keep_alive else None
    if not _watch["dirty"]:
        return _TIMER_INTERVAL
    if _deferring():
        # The move is not over. Blender keys when the transform CONFIRMS, so
        # the pending key is owed then — it is kept, never dropped.
        return _TIMER_INTERVAL
    if time.monotonic() - _watch["changed_at"] < DEBOUNCE_SECONDS:
        return _TIMER_INTERVAL
    sig = camera_signature(shot.camera)
    if sig != _watch["sig"]:
        _watch.update({"sig": sig, "changed_at": time.monotonic()})
        return _TIMER_INTERVAL
    _watch["dirty"] = False
    # Blender's "only insert needed": a move that settled back on the pose
    # this frame already holds — the baseline, or the last thing captured —
    # has nothing to key.
    if sig in (_watch["captured_sig"], _watch["baseline"]):
        return _TIMER_INTERVAL

    from .capture import capture_beat

    try:
        beat = capture_beat(
            bpy.context, shot, state.beat_seconds, replace_existing=True
        )
    except Exception:
        logger.exception("Auto Key could not capture a keyframe")
        return _TIMER_INTERVAL
    logger.info("Auto Key captured frame %s", beat.frame)
    _watch["frame"] = int(scene.frame_current)
    _watch["sig"] = camera_signature(shot.camera)
    _watch["baseline"] = _watch["sig"]
    return _TIMER_INTERVAL


def _ensure_timer() -> None:
    if not bpy.app.timers.is_registered(_debounce_timer):
        bpy.app.timers.register(_debounce_timer, first_interval=_TIMER_INTERVAL)


def register() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update not in handlers:
        handlers.append(_on_depsgraph_update)


def unregister() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update in handlers:
        handlers.remove(_on_depsgraph_update)
    if bpy.app.timers.is_registered(_debounce_timer):
        bpy.app.timers.unregister(_debounce_timer)
    _reset()
    _watch["captured_sig"] = None
