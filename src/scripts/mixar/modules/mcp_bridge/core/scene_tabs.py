# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Scene tabs for MCP clients, created, switched and closed the way the Scenes drawer does.

Main thread only (the UI-control pump runs these). A tab made here is the same
as one from "+ New scene": ready while connected, the signed-in account, the
current tab's settings, a camera and a light. It also gets its session id at
once, because the connector pins MCP calls to a session, not to a window.
"""

import uuid

import bpy

from mixar.modules.common.ui_control.constants import MAX_SCENES, UIError


def _ops():
    from mixar.modules.space_mixie_chat.ui.operators import scene_tab_ops
    return scene_tab_ops


def _session():
    from mixar.modules.space_mixie_chat.core.session import get_session_manager
    return get_session_manager()


def _ensure_session_id(scene) -> str:
    if not getattr(scene, "mixie_session_id", ""):
        scene.mixie_session_id = str(uuid.uuid4())
    return scene.mixie_session_id


def _shown():
    from mixar.modules.common.ui_control.core.observe import main_window
    return main_window().scene


def _entry(scene, shown) -> dict:
    return {"name": scene.name, "session": _ensure_session_id(scene),
            "state": _session().get_state(scene).value, "shown": scene is shown}


# Mixar's own modals while an agent works in a tab: they guard that tab and
# stand down by themselves once the window shows another, as with the drawer's
# "+ New scene". Only an operation the user has open blocks a tab change.
AGENT_MODALS = frozenset({
    "MIXAR_OT_agent_viewport_block", "mixar.agent_viewport_block",
    "MIXIE_CHAT_OT_undo_shield", "mixie_chat.undo_shield",
})


def _user_modal(wm) -> bool:
    return any(getattr(op, "bl_idname", "") not in AGENT_MODALS
               for window in wm.windows for op in getattr(window, "modal_operators", ()))


def _gate():
    """Switching what every window shows must not cut into other work. Another
    tab's agent keeps working off screen, so it does not block."""
    from mixar.modules.common.render_coordinator.core import busy
    from mixar.modules.common.ui_control.core import ownership
    if busy():
        raise UIError("render_in_progress", "Wait for the render to finish")
    wm = bpy.context.window_manager
    if getattr(wm, "mixar_window_resizing", False):
        raise UIError("ui_busy", "Wait for window resize to finish")
    if ownership.active():
        raise UIError("ui_busy", "Release UI control before changing scenes")
    if _user_modal(wm):
        raise UIError("ui_busy", "The user has an operation open in Mixar (a dialog, a transform or a "
                                 "paint stroke); ask them to finish or cancel it, then try again")


def _refresh_drawer():
    from mixar.modules.space_mixie_chat.ui.properties.scene_tabs_props import refresh_scene_tabs
    refresh_scene_tabs()


def _working(scene) -> bool:
    """Mixie's turn or run in that tab (what the drawer would stop on close)."""
    from mixar.modules.space_mixie_chat.constants import SessionState
    session = _session()
    return (session.get_state(scene) in (SessionState.BUSY, SessionState.MODIFYING,
                                         SessionState.AWAITING_INPUT)
            or bool(session.run_open(scene)))


def _content(scene) -> list:
    """What closing would lose: every object but the camera and light a tab
    starts with. The chat is not lost — closing archives it to History."""
    return [obj for obj in scene.objects if getattr(obj, "type", "") not in ("CAMERA", "LIGHT")]


def _target(session: str):
    matches = [scene for scene in _ops().real_scenes() if getattr(scene, "mixie_session_id", "") == session]
    if len(matches) != 1:
        raise UIError("scene_unavailable", "No single scene tab has that session; list them with mixar_scenes")
    return matches[0]


def _refuse_at_limit():
    """Final, and names the way out: a scripted client that retried this
    refusal spun on it for minutes."""
    shown, count = _shown(), len(_ops().real_scenes())
    reuse = [_entry(scene, shown) for scene in _ops().ordered_tabs()]
    reuse.sort(key=lambda entry: entry["state"] != "idle")  # Idle tabs first; stable otherwise.
    raise UIError("scene_limit",
                  f"Mixar has {count} scene tabs (limit {MAX_SCENES}). Do not retry mixar_scene_new: switch to "
                  "an existing tab with mixar_scene_switch (sessions in reuse), close one you no longer need "
                  "with mixar_scene_close (ask the user first if it holds their work), or ask the user to "
                  "close tabs in Mixar's Scenes drawer",
                  {"retryable": False, "scene_count": count, "max_scenes": MAX_SCENES, "reuse": reuse})


def preflight(name: str, args: dict) -> None:
    """Every refusal happens before the call is claimed, so a refused call has
    a clean "failed" receipt instead of an uncertain one."""
    _gate()
    if name == "mixar_scene_new" and len(_ops().real_scenes()) >= MAX_SCENES:
        _refuse_at_limit()
    if name == "mixar_scene_switch":
        _target(args["session"])
    if name == "mixar_scene_close":
        _closable(args)


def _closable(args: dict):
    """A tab an AI app may close: not the last, nobody working in it, and its
    objects discarded only with consent (the mixar_project_open convention)."""
    from . import lease
    scene = _target(args["session"])
    if len(_ops().real_scenes()) <= 1:
        raise UIError("last_scene", "This is the only scene tab; Mixar keeps at least one open")
    if _working(scene) or lease.held(args["session"]):
        raise UIError("scene_busy", "An agent (Mixie, or another AI app connection) is working in that tab, "
                                    "so it was not closed. Wait for it to finish, or ask the user to stop it")
    content = _content(scene)
    if content and args.get("contents", "refuse") != "discard":
        raise UIError("scene_has_content",
                      f"That tab holds {len(content)} object(s) that closing would delete. Ask the user whether "
                      "to discard them, then call again with contents='discard'. Only a tab holding nothing but "
                      "work you made in this conversation may be discarded without asking")
    return scene


def list_scenes() -> dict:
    shown = _shown()
    return {"scenes": [_entry(scene, shown) for scene in _ops().ordered_tabs()]}


def new_scene(name: str = "") -> dict:
    preflight("mixar_scene_new", {})
    scene = _ops().new_scene_tab(name)
    from mixar.modules.space_mixie_chat.core.scene_identity import adopt_scene
    adopt_scene(scene)  # A tab made mid-reconnect becomes ready once connected.
    return _entry(scene, _shown())


def switch_scene(session: str) -> dict:
    preflight("mixar_scene_switch", {"session": session})
    scene = _target(session)
    _ops().switch_scene_tab(scene, was=_shown())
    from mixar.modules.space_mixie_chat.core.scene_identity import adopt_scene
    adopt_scene(scene)
    return _entry(scene, _shown())


def close_scene(session: str, contents: str = "refuse") -> dict:
    """Close a tab the drawer's way — its chat archived to History, its worker
    lanes swept, windows showing it moved to a neighbour. Returns the tab now
    shown, plus the closed one."""
    preflight("mixar_scene_close", {"session": session, "contents": contents})
    scene = _target(session)
    name = scene.name
    closed, reason = _ops().close_scene_tab(scene)
    if not closed:
        raise UIError("close_failed", reason or "Mixar could not close that tab")
    _refresh_drawer()
    shown = _shown()
    return {**_entry(shown, shown), "closed": {"name": name, "session": session}}
