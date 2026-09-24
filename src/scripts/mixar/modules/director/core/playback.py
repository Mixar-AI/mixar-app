# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Playback that ends at the scene's end frame instead of looping.

Blender's animation player always wraps: at the end of the frame (or preview)
range the playhead jumps back to the start and keeps going. That is right for
an animator checking a cycle and wrong for a director reviewing a shot — the
Preview button is "play this shot", not "loop this shot forever".

Director therefore ARMS a one-shot stop (``arm_single_play``), records the
frame the range ends on, and a ``frame_change_post`` handler stops the player
the moment the playhead reaches or passes it. Nothing here is global: the arming
only happens while a session is DIRECTING, so ordinary Blender playback keeps
looping exactly as the user expects everywhere else.

Every route into playback is armed, not just the Preview button — pressing
Space over the viewport is the same request, and a timeline that runs forever
is the same wrong answer whichever button started it. ``animation_playback_pre``
is where that happens, and it never overrides an arming the Preview button
already made.

The decision is a pure function (``should_stop``) so the wrap case — the player
having already bounced back past the start before the handler is reached — is
pinned by tests without a running Blender. That case is only sound once the
playhead has been seen PAST the start: the player's first notification after
``animation_play`` is often the start frame itself, and reading that as a
completed wrap stopped Preview dead and parked it on the last keyframe.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Set by `arm_single_play`; cleared the moment playback is stopped, cancelled,
# or the scene it was armed for goes away. `None` means "not our playback".
_armed: dict = {
    "scene": None,
    "name": "",
    "end_frame": 0,
    "start_frame": 0,
    #: Has the playhead been SEEN past the start since this arming? The wrap
    #: rule below is only sound once it has — see `should_stop`.
    "advanced": False,
}
#: Re-entrancy guard: `_stop_playback` calls `frame_set`, which fires
#: `frame_change_post` again from inside this very handler.
_stopping = {"busy": False}


def is_armed() -> bool:
    return _armed["scene"] is not None


def arm_single_play(scene, start_frame: int, end_frame: int) -> None:
    """Ask the next playback of *scene* to stop at *end_frame*."""
    _armed["scene"] = scene.as_pointer() if hasattr(scene, "as_pointer") else id(scene)
    # The handler's scene argument is not guaranteed to be the same PyObject,
    # so the name is carried as a second key. Either matching is enough.
    _armed["name"] = getattr(scene, "name", "")
    _armed["start_frame"] = int(start_frame)
    _armed["end_frame"] = int(end_frame)
    _armed["advanced"] = False


def disarm() -> None:
    _armed["scene"] = None
    _armed["name"] = ""
    _armed["start_frame"] = 0
    _armed["end_frame"] = 0
    _armed["advanced"] = False


def _is_armed_scene(scene) -> bool:
    if scene is None or not is_armed():
        return False
    pointer = scene.as_pointer() if hasattr(scene, "as_pointer") else id(scene)
    if pointer == _armed["scene"]:
        return True
    name = getattr(scene, "name", "")
    return bool(name) and name == _armed["name"]


def should_stop(
    frame: int, start_frame: int, end_frame: int, advanced: bool = True
) -> bool:
    """Has the armed playback reached its end?

    Two cases, and the second is the one a naive ``frame >= end`` misses.

    1. The handler sees the end frame itself (the common case at any frame
       step of 1).
    2. The player has already WRAPPED and the handler sees a frame back at the
       start. Blender advances first and notifies after, so with a frame step
       greater than one, or a dropped frame under load, the end frame is never
       reported at all — only the wrapped one. A frame at or before the start
       while the range runs forward therefore means the loop closed.

    *advanced* is what makes case 2 sound, and leaving it out made Preview
    LOOK like it did nothing but jump to the last keyframe: a frame back at
    the start only means the loop closed if the playhead ever LEFT the start.
    The player's first notification after `animation_play` is frequently the
    start frame itself — a zero-sized step in a sync/frame-drop mode, or the
    re-notify Blender does when the frame was just set — so the very first
    handler call read as a completed wrap, stopped the player and parked the
    playhead on the end frame before a single frame had been shown.

    A range of one frame can never wrap, so it only uses case 1.
    """
    if end_frame <= start_frame:
        return frame >= end_frame
    if frame >= end_frame:
        return True
    if not advanced:
        return False
    return frame <= start_frame


def _stop_playback(scene, frame: int) -> None:
    disarm()
    _stopping["busy"] = True
    try:
        try:
            bpy.ops.screen.animation_cancel(restore_frame=False)
        except Exception:
            logger.exception("Director preview could not stop the animation player")
            return
        try:
            # Park exactly on the last keyframe. This fires `frame_change_post`
            # again from inside it, which `_stopping` absorbs.
            scene.frame_set(int(frame))
        except Exception:
            logger.exception("Director preview could not park the playhead")
    finally:
        _stopping["busy"] = False


def _tag_director_docks(scene) -> None:
    """Keep the dock's playhead moving while the player runs.

    Blender suppresses notifiers during playback and tags regions itself
    (`ED_match_region_with_redraws`), which knows about WINDOW and UI regions
    of the editors it ships — and nothing about a `RGN_TYPE_CHANNELS` region
    inside a View3D, which is what the Director dock is. So the dock's own
    listener never fired during playback: the viewport played, the dock's
    playhead stood still, and it appeared at the last keyframe only when the
    stop parked it there. That reads as "Preview jumps to the end".

    One redraw tag per frame change, and only while a Director session is
    live, so a file that never opens Director pays a single attribute read.
    """
    state = getattr(scene, "mixar_director", None)
    if state is None or not getattr(state, "is_directing", False):
        return
    # `bpy.data`, not `bpy.context`: a frame-change handler runs with
    # whatever context Blender happens to be in, and this file has already
    # been bitten once by deciding from it.
    for wm in bpy.data.window_managers:
        for window in wm.windows:
            screen = getattr(window, "screen", None)
            if screen is None:
                continue
            for area in screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                for region in area.regions:
                    if region.type == 'CHANNELS':
                        region.tag_redraw()


@persistent
def _on_frame_change(scene, _depsgraph=None) -> None:
    from .record import recording_suspended

    if _stopping["busy"] or recording_suspended():
        return
    # Every playback route, not just Preview: pressing Space over the
    # viewport must move the dock's playhead too.
    try:
        _tag_director_docks(scene)
    except Exception:  # noqa: BLE001 — a redraw tag must never break playback
        logger.debug("Director dock redraw tag skipped", exc_info=True)
    if not _is_armed_scene(scene):
        return
    frame = int(scene.frame_current)
    if should_stop(frame, _armed["start_frame"], _armed["end_frame"], _armed["advanced"]):
        _stop_playback(scene, _armed["end_frame"])
        return
    # Only now is a later frame back at the start a wrap rather than a player
    # that has not moved yet.
    if frame > _armed["start_frame"]:
        _armed["advanced"] = True


@persistent
def _on_playback_start(scene, _depsgraph=None) -> None:
    """Any playback in a Director session plays the range ONCE.

    The Preview button arms itself before it starts the player, so an
    existing arming is left alone; this is for every other route in, Space
    over the viewport being the one a director actually uses.
    """
    if is_armed():
        return
    state = getattr(scene, "mixar_director", None)
    if state is None or not getattr(state, "is_directing", False):
        return
    start = int(getattr(scene, "frame_start", 0))
    end = int(getattr(scene, "frame_end", 0))
    if end <= start:
        return
    arm_single_play(scene, start, end)


@persistent
def _on_playback_end(_scene, _depsgraph=None) -> None:
    """Playback ended by any route — the transport, Esc, another operator.

    This is the ONLY thing that disarms on a stop. The handler used to check
    `bpy.context.screen.is_animation_playing` and disarm when it read False,
    but a frame-change handler runs with whatever context Blender happens to
    be in: on a screen that is not the playing one that read False on the very
    first frame change, disarmed immediately, and the preview then looped
    forever — the bug this replaces.
    """
    disarm()


@persistent
def _on_load(_file) -> None:
    disarm()
    _stopping["busy"] = False


_HANDLERS = (
    ("frame_change_post", "_on_frame_change"),
    ("animation_playback_pre", "_on_playback_start"),
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
    disarm()
    _stopping["busy"] = False
