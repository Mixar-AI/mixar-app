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
ordinary update storm). The handler itself only notices the growth: the
property writes of a detach run from a ``bpy.app.timers`` callback, never
inside the depsgraph handler (the handler-pattern rule).

Scene datablock audit
---------------------
The same timer first logs what changed: one ``[SCENES] scene.added`` line per
scene that appeared (objects, world, camera, session id, custom keys, the
window's scene, the last operators that ran) and one ``scene.removed`` per
scene that is gone. Blender's own New Scene → Copy Settings, a worker's
workspace, a tab, an appended scene: every path that makes a scene shows up
here with the operator that made it, so a phantom ``<tab>.001`` is
attributable from the log file alone.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.common.scenes_log import slog

from ..constants import SessionState

logger = get_logger(__name__)

_last_scene_count: int = -1
#: Scene names at the last audit; the diff against the live list names what
#: appeared or vanished. A rename shows as one removed + one added line.
_known_scene_names: set = set()
# Custom props that identify THIS scene's conversation and document identity.
_COPIED_PROPS = ("mixie_ws_resume", "mixar_scene_id")
#: Operators a scene audit line reports, newest last.
_OPERATOR_HISTORY = 3
_KEYS_LIMIT = 16


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


def _str(value) -> str:
    """A short, safe string of a Blender value for a log field."""
    try:
        text = value if isinstance(value, str) else getattr(value, "name", None) or str(value)
    except Exception:  # noqa: BLE001
        return "?"
    return text[:120]


def _recent_operators() -> list:
    """``bl_idname`` of the last operators Blender ran (newest last): the
    strongest hint about who made a scene. Empty when unavailable."""
    try:
        ops = list(bpy.context.window_manager.operators)[-_OPERATOR_HISTORY:]
        names = [getattr(op, "bl_idname", "") for op in ops]
        return [n for n in names if isinstance(n, str) and n]
    except Exception:  # noqa: BLE001
        return []


def describe_scene(scene) -> dict:
    """The audit fields of one scene: enough to tell a Copy Settings copy
    (shared world, no objects, copied session id) from a Mixar tab (own
    world, camera + light) from a worker workspace (``mixar_workspace_*``)."""
    fields: dict = {}
    try:
        fields["objects"] = len(scene.objects)
    except Exception:  # noqa: BLE001
        fields["objects"] = -1
    try:
        fields["world"] = _str(scene.world) if getattr(scene, "world", None) is not None else ""
    except Exception:  # noqa: BLE001
        fields["world"] = "?"
    try:
        fields["camera"] = _str(scene.camera) if getattr(scene, "camera", None) is not None else ""
    except Exception:  # noqa: BLE001
        fields["camera"] = "?"
    try:
        keys = [str(k) for k in scene.keys()]
        fields["keys"] = ",".join(keys[:_KEYS_LIMIT]) + ("…" if len(keys) > _KEYS_LIMIT else "")
    except Exception:  # noqa: BLE001
        fields["keys"] = "?"
    try:
        fields["users"] = int(scene.users)
    except Exception:  # noqa: BLE001
        pass
    return fields


def _window_scene_name() -> str:
    try:
        window = bpy.context.window
        return _str(window.scene) if window is not None and window.scene is not None else ""
    except Exception:  # noqa: BLE001
        return ""


def audit_scenes() -> tuple:
    """Log every scene that appeared or vanished since the last audit.
    Returns ``(added names, removed names)``. Never raises."""
    global _known_scene_names
    try:
        scenes = list(bpy.data.scenes)
    except Exception:  # noqa: BLE001
        return [], []
    by_name = {}
    for scene in scenes:
        try:
            by_name[str(scene.name)] = scene
        except Exception:  # noqa: BLE001
            continue
    current = set(by_name)
    added = sorted(current - _known_scene_names)
    removed = sorted(_known_scene_names - current)
    _known_scene_names = current
    if not added and not removed:
        return added, removed
    operators = ",".join(_recent_operators()) or "-"
    window_scene = _window_scene_name()
    for name in added:
        scene = by_name[name]
        try:
            slog("scene.added", scene, tabs=len(scenes), window_scene=window_scene,
                 operators=operators, **describe_scene(scene))
        except Exception:  # noqa: BLE001
            logger.debug("scene audit line skipped for %r", name, exc_info=True)
    for name in removed:
        try:
            slog("scene.removed", None, name=name, tabs=len(scenes), window_scene=window_scene,
                 operators=operators)
        except Exception:  # noqa: BLE001
            logger.debug("scene audit line skipped for %r", name, exc_info=True)
    return added, removed


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
        _schedule_audit()
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
    """Timer body: audit what appeared, then one scan; the timer unregisters
    (returns None)."""
    try:
        audit_scenes()
    except Exception:  # noqa: BLE001 — the audit must not block the scan
        logger.debug("scene audit failed", exc_info=True)
    try:
        dedupe_session_ids()
    except Exception:  # noqa: BLE001 — a failed scan must not kill the timer host
        logger.debug("session dedupe failed", exc_info=True)
    return None


def _audit_later():
    """Timer body for a shrink: log what vanished, then unregister."""
    try:
        audit_scenes()
    except Exception:  # noqa: BLE001
        logger.debug("scene audit failed", exc_info=True)
    return None


def _schedule_audit() -> None:
    try:
        if not bpy.app.timers.is_registered(_audit_later):
            bpy.app.timers.register(_audit_later, first_interval=0.0)
    except Exception:  # noqa: BLE001 — no timer host: audit inline
        audit_scenes()


def _schedule_dedupe() -> None:
    try:
        if not bpy.app.timers.is_registered(_dedupe_later):
            bpy.app.timers.register(_dedupe_later, first_interval=0.0)
    except Exception:  # noqa: BLE001 — no timer host (tests, shutdown): scan inline
        dedupe_session_ids()


@persistent
def _on_load_post(*_args) -> None:
    global _last_scene_count, _known_scene_names
    try:
        _last_scene_count = len(bpy.data.scenes)
        # A loaded file is the baseline, not a burst of "added" lines.
        _known_scene_names = {str(s.name) for s in bpy.data.scenes}
    except Exception:  # noqa: BLE001
        _last_scene_count = -1
        _known_scene_names = set()
    slog("scenes.loaded", None, tabs=_last_scene_count,
         names=",".join(sorted(_known_scene_names))[:400])
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
