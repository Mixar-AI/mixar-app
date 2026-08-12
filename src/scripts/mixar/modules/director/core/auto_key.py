# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Debounced automatic keyframe capture for Precise-mode camera edits.

Navigate-mode auto keys come from the walk supervisor, which knows exactly
when a move ends. Precise mode has no such boundary — gizmo drags stream
depsgraph updates — so a handler marks the camera dirty and a timer captures
once the camera has been still for ``DEBOUNCE_SECONDS``. A frame change
rebaselines instead of dirtying: scrubbing or playback moves the camera
through its animation, and capturing those poses would duplicate keys the
user never authored.
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
    _watch.update({"key": key, "frame": frame, "sig": sig, "dirty": False})


def _watchable_shot(scene):
    state = getattr(scene, "mixar_director", None)
    if (
        state is None
        or not state.is_directing
        or not state.auto_key
        or state.navigation_mode != 'PRECISE'
    ):
        return None, None
    shot = active_shot(scene)
    if shot is None or shot.state != 'DRAFT' or shot.camera is None:
        return None, None
    return state, shot


@persistent
def _on_depsgraph_update(scene, _depsgraph) -> None:
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
    if time.monotonic() - _watch["changed_at"] < DEBOUNCE_SECONDS:
        return _TIMER_INTERVAL
    sig = camera_signature(shot.camera)
    if sig != _watch["sig"]:
        _watch.update({"sig": sig, "changed_at": time.monotonic()})
        return _TIMER_INTERVAL
    _watch["dirty"] = False
    if sig == _watch["captured_sig"]:
        return _TIMER_INTERVAL

    from .capture import capture_beat

    try:
        beat = capture_beat(bpy.context, shot, state.beat_seconds)
    except Exception:
        logger.exception("Auto Key could not capture a keyframe")
        return _TIMER_INTERVAL
    logger.info("Auto Key captured frame %s", beat.frame)
    _watch["frame"] = int(scene.frame_current)
    _watch["sig"] = camera_signature(shot.camera)
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
