# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Scene tabs for MCP clients, created and switched the way the Scenes drawer does.

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


def _gate():
    """Switching what every window shows must not cut into other work."""
    from mixar.modules.common.render_coordinator.core import busy
    from mixar.modules.common.ui_control.core import ownership
    if busy():
        raise UIError("render_in_progress", "Wait for the render to finish")
    wm = bpy.context.window_manager
    if getattr(wm, "mixar_window_resizing", False):
        raise UIError("ui_busy", "Wait for window resize to finish")
    if ownership.active():
        raise UIError("ui_busy", "Release UI control before changing scenes")
    if any(getattr(window, "modal_operators", ()) for window in wm.windows):
        raise UIError("ui_busy", "Finish the current modal operation before changing scenes")


def _target(session: str):
    matches = [scene for scene in _ops().real_scenes() if getattr(scene, "mixie_session_id", "") == session]
    if len(matches) != 1:
        raise UIError("scene_unavailable", "No single scene tab has that session; list them with mixar_scenes")
    return matches[0]


def preflight(name: str, args: dict) -> None:
    """Every refusal happens before the call is claimed, so a refused call has
    a clean "failed" receipt instead of an uncertain one."""
    _gate()
    if name == "mixar_scene_new" and len(_ops().real_scenes()) >= MAX_SCENES:
        raise UIError("scene_limit", f"Mixar already has {MAX_SCENES} scene tabs; reuse or close one")
    if name == "mixar_scene_switch":
        _target(args["session"])


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
