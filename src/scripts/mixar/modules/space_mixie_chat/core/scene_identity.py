# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One chat session per scene, enforced.

Blender's Scene → Copy (and ``bpy.ops.scene.new(type='FULL_COPY')``) copies
every scene property, including ``mixie_session_id``, the transcript and the
resume cursor. Two scenes then claim one backend session: scripts route to
whichever matches first and turn events cannot bind. ``dedupe_session_ids``
keeps the original and turns every copy into a fresh, empty chat.

A scene created any other way than the drawer's "+ New scene" (a script,
an add-on, Blender's New Scene) is adopted by ``adopt_scene``: while
connected it starts IDLE with the signed-in account, like a drawer tab.

Runs after a file loads and whenever the scene count changes
(``depsgraph_update_post``; a length compare, so it costs nothing on the
ordinary update storm). The handler itself only notices the growth: the
property writes of a detach run from a ``bpy.app.timers`` callback, never
inside the depsgraph handler (the handler-pattern rule).
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.common.scenes_log import slog

from ..constants import SessionState, is_lane_scene

logger = get_logger(__name__)

_last_scene_count: int = -1
# Custom props that identify THIS scene's conversation and document identity.
_COPIED_PROPS = ("mixie_ws_resume", "mixar_scene_id")
#: Login identity the auth flow stamps on the scene it signed in from; a new
#: scene inherits it, or the profile chip and credits read blank there.
ACCOUNT_PROPS = ("mixie_chat_user_id", "mixie_chat_credits", "mixie_chat_model")


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


def inherit_account(source, scene) -> None:
    """Copy the signed-in identity from ``source`` onto a new scene."""
    if source is None or source is scene:
        return
    for prop in ACCOUNT_PROPS:
        try:
            setattr(scene, prop, getattr(source, prop))
        except Exception:  # noqa: BLE001 — a missing property on either side is fine
            pass


def _connection_live() -> bool:
    try:
        from .connection_manager import get_connection_manager
        connected = get_connection_manager().is_connected
        return bool(connected() if callable(connected) else connected)
    except Exception:  # noqa: BLE001
        return False


def _account_source(scene):
    window = getattr(getattr(bpy.context, "window", None), "scene", None)
    for candidate in [window, *bpy.data.scenes]:
        if (candidate is not None and candidate is not scene and not is_lane_scene(candidate)
                and getattr(candidate, "mixie_chat_user_id", "")):
            return candidate
    return None


def adopt_scene(scene) -> bool:
    """Make a scene that appeared while Mixar is connected ready for work.

    ``mixie_chat_state`` defaults to OFFLINE and only the WebSocket connect
    promotes scenes to IDLE, so a scene made by ``bpy.data.scenes.new`` (an
    agent or MCP script, an add-on, Blender's own New Scene) stayed OFFLINE
    until the next reconnect, and chat, MCP scene tools and UI control all
    refused it. While connected, OFFLINE on a real scene with no open run means
    exactly that; the transport-drop paths set OFFLINE only once disconnected.
    Agent lane scenes are workers' private copies and are never adopted.
    """
    from .session import get_session_manager

    if scene is None or is_lane_scene(scene):
        return False
    session = get_session_manager()
    if session.get_state(scene) != SessionState.OFFLINE or session.run_open(scene):
        return False
    if not _connection_live():
        return False
    if not getattr(scene, "mixie_chat_user_id", ""):
        inherit_account(_account_source(scene), scene)
    session.set_connected(scene)
    slog("tab.adopt", scene)
    logger.info("Scene %r appeared while connected: ready for chat and MCP", scene.name)
    return True


def adopt_new_scenes() -> list[str]:
    """Adopt every OFFLINE real scene while connected. Returns their names."""
    return [scene.name for scene in list(bpy.data.scenes) if adopt_scene(scene)]


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
    shrank = _last_scene_count >= 0 and count < _last_scene_count
    _last_scene_count = count
    if grew:
        _schedule_dedupe()
    if shrank:
        _prune_active_sessions()


def _prune_active_sessions() -> None:
    """A scene deleted outside `close_scene_tab` (Outliner, a script, undo)
    never reaches IDLE: drop its active-session entry here, on the main
    thread, so `has_active_session` stops reporting a running agent."""
    try:
        from .session import SessionManager
        gone = SessionManager.prune_missing_scenes()
        if gone:
            logger.info("active-session entries pruned for deleted scenes: %s", gone)
    except Exception:  # noqa: BLE001
        logger.debug("active-session prune failed", exc_info=True)


def _dedupe_later():
    """Timer body: one scan, then the timer unregisters (returns None)."""
    try:
        dedupe_session_ids()
    except Exception:  # noqa: BLE001 — a failed scan must not kill the timer host
        logger.debug("session dedupe failed", exc_info=True)
    try:
        adopt_new_scenes()
    except Exception:  # noqa: BLE001
        logger.debug("new scene adoption failed", exc_info=True)
    return None


def _schedule_dedupe() -> None:
    try:
        if not bpy.app.timers.is_registered(_dedupe_later):
            bpy.app.timers.register(_dedupe_later, first_interval=0.0)
    except Exception:  # noqa: BLE001 — no timer host (tests, shutdown): scan inline
        dedupe_session_ids()


@persistent
def _on_load_post(*_args) -> None:
    global _last_scene_count
    try:
        _last_scene_count = len(bpy.data.scenes)
    except Exception:  # noqa: BLE001
        _last_scene_count = -1
    dedupe_session_ids()
    _prune_active_sessions()


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
