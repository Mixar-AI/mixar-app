# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drop shots whose camera was deleted outside Director.

Deleting a camera from the outliner, the viewport, or a script clears every
RNA pointer to it, so the shot survives as a take that directs nothing: the
timeline keeps its strip, the session keeps counting it, and "+ Add Camera"
mints another beside it.

Detection is a REMEMBERED TRANSITION, not "camera is None". A shot can be
legitimately camera-less for a moment while a session is being built, and a
file saved before this watcher existed would otherwise lose shots on load. The
handler records which shots it has seen holding a camera (module state, keyed
by the stable `shot_id`), and only a shot that HAD one and now has none is a
deletion.

Split the way `beat_sync` is, and for the same reason: the depsgraph handler
only *detects* — mutating scene data inside ``depsgraph_update_post`` is
unsafe — and a debounced timer does the removal.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

from .shot_api import remove_shot

logger = get_logger(__name__)

_TIMER_INTERVAL = 0.1

# shot_id -> the shot was last seen holding a camera.
_seen: dict[str, bool] = {}
_pending = {"prune": False}


def orphaned_shot_indices(state) -> list[int]:
    """Indices of shots that HELD a camera and no longer do.

    Pure over the remembered set so the decision is testable without Blender:
    the caller's `_seen` is what turns "no camera" into "camera deleted".
    """
    if state is None:
        return []
    orphaned = []
    for index, shot in enumerate(state.shots):
        shot_id = getattr(shot, "shot_id", "")
        if not shot_id:
            continue
        if getattr(shot, "camera", None) is not None:
            continue
        if _seen.get(shot_id):
            orphaned.append(index)
    return orphaned


def _observe(state) -> None:
    """Refresh the remembered set from the shots as they stand now."""
    live = set()
    for shot in getattr(state, "shots", ()):
        shot_id = getattr(shot, "shot_id", "")
        if not shot_id:
            continue
        live.add(shot_id)
        if getattr(shot, "camera", None) is not None:
            _seen[shot_id] = True
    # Shots that are gone take their memory with them; the dict must not grow
    # for the life of the session.
    for shot_id in [key for key in _seen if key not in live]:
        del _seen[shot_id]


def _redraw() -> None:
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()):
            if area.type in {'VIEW_3D', 'MIXIE'}:
                area.tag_redraw()


@persistent
def _on_depsgraph_update(scene, _depsgraph=None) -> None:
    state = getattr(scene, "mixar_director", None)
    if state is None:
        return
    if orphaned_shot_indices(state):
        _pending["prune"] = True
        _ensure_timer()
    _observe(state)


def _prune_timer():
    if not _pending["prune"]:
        return None
    _pending["prune"] = False
    scene = getattr(bpy.context, "scene", None)
    state = getattr(scene, "mixar_director", None) if scene is not None else None
    if state is None:
        return None
    # Highest index first: `shots.remove(i)` shifts everything after i.
    orphaned = sorted(orphaned_shot_indices(state), reverse=True)
    if not orphaned:
        return None
    try:
        for index in orphaned:
            remove_shot(scene, index)
    except Exception:
        logger.exception("Could not drop shots whose camera was deleted")
        return None
    logger.info("Dropped %s shot(s) whose camera was deleted", len(orphaned))
    _observe(state)
    _redraw()
    return None


def _ensure_timer() -> None:
    if not bpy.app.timers.is_registered(_prune_timer):
        bpy.app.timers.register(_prune_timer, first_interval=_TIMER_INTERVAL)


@persistent
def _on_load(_file) -> None:
    # A new file's shot ids mean nothing to the old file's memory, and a shot
    # that loads camera-less must not read as a deletion this session caused.
    _seen.clear()
    _pending["prune"] = False


def register() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update not in handlers:
        handlers.append(_on_depsgraph_update)
    load_handlers = bpy.app.handlers.load_post
    if _on_load not in load_handlers:
        load_handlers.append(_on_load)


def unregister() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    if _on_depsgraph_update in handlers:
        handlers.remove(_on_depsgraph_update)
    load_handlers = bpy.app.handlers.load_post
    if _on_load in load_handlers:
        load_handlers.remove(_on_load)
    if bpy.app.timers.is_registered(_prune_timer):
        bpy.app.timers.unregister(_prune_timer)
    _seen.clear()
    _pending["prune"] = False
