# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One chat session per scene, enforced.

Blender's Scene → Copy (and ``bpy.ops.scene.new(type='FULL_COPY')``) copies
every scene property, including ``mixie_session_id``, the transcript and the
resume cursor. Two scenes then claim one backend session: scripts route to
whichever matches first and turn events cannot bind. ``dedupe_session_ids``
keeps the original and turns every copy into a fresh, empty chat.

Runs after a file loads and whenever the scene count changes
(``depsgraph_update_post``; a length compare, so it costs nothing on the
ordinary update storm).
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.common.scenes_log import slog

from ..constants import SessionState

logger = get_logger(__name__)

_last_scene_count: int = -1
# Custom props that identify THIS scene's conversation and document identity.
_COPIED_PROPS = ("mixie_ws_resume", "mixar_scene_id")


def _original(scenes):
    """Which of several scenes sharing a session id is the original: the one
    turn events are bound to, else the one with the shortest name (Blender
    names a copy ``<name>.001``)."""
    try:
        from .turn_events import _bindings, _scene_id
        sid = getattr(scenes[0], "mixie_session_id", "")
        bound = _bindings.get(sid)
        if bound is not None:
            for scene in scenes:
                if _scene_id(scene) == bound:
                    return scene
    except Exception:  # noqa: BLE001
        pass
    return min(scenes, key=lambda s: (len(s.name), s.name))


def detach_copy(scene, was: str) -> None:
    """Make ``scene`` a fresh chat: no session, no transcript, no run."""
    from .session import get_session_manager

    scene.mixie_session_id = ""
    try:
        scene.mixie_chat_messages.clear()
    except Exception:  # noqa: BLE001
        pass
    session = get_session_manager()
    try:
        session.set_run(scene, "", False)
        session.set_state(scene, SessionState.IDLE)
    except Exception:  # noqa: BLE001
        pass
    for attr, value in (("mixie_chat_input", ""), ("mixie_checkpoint_session_id", ""),
                        ("mixie_chat_user_has_engaged", False)):
        if hasattr(scene, attr):
            try:
                setattr(scene, attr, value)
            except Exception:  # noqa: BLE001
                pass
    for key in _COPIED_PROPS:
        try:
            if key in scene:
                del scene[key]
        except Exception:  # noqa: BLE001
            pass
    slog("tab.dedupe", scene, was=was)
    logger.info("Scene %r was a copy of the chat session %s: detached as a new chat", scene.name, was[:8])


def dedupe_session_ids(scenes=None) -> list[str]:
    """Detach every scene that shares a session id with another. Returns the
    detached scene names."""
    by_sid: dict[str, list] = {}
    for scene in (scenes if scenes is not None else bpy.data.scenes):
        sid = getattr(scene, "mixie_session_id", "") or ""
        if sid:
            by_sid.setdefault(sid, []).append(scene)
    detached = []
    for sid, group in by_sid.items():
        if len(group) < 2:
            continue
        keep = _original(group)
        for scene in group:
            if scene is not keep:
                detach_copy(scene, sid)
                detached.append(scene.name)
    return detached


@persistent
def _on_depsgraph_update(*_args) -> None:
    global _last_scene_count
    try:
        count = len(bpy.data.scenes)
    except Exception:  # noqa: BLE001
        return
    if count == _last_scene_count:
        return
    grew = _last_scene_count >= 0 and count > _last_scene_count
    _last_scene_count = count
    if grew:
        dedupe_session_ids()


@persistent
def _on_load_post(*_args) -> None:
    global _last_scene_count
    try:
        _last_scene_count = len(bpy.data.scenes)
    except Exception:  # noqa: BLE001
        _last_scene_count = -1
    dedupe_session_ids()


def register() -> None:
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister() -> None:
    for handlers, fn in ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update),
                         (bpy.app.handlers.load_post, _on_load_post)):
        if fn in handlers:
            handlers.remove(fn)
