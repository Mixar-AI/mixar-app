# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Main-thread admission shared with scene operations; no waiting under a lock."""

import bpy

from ..constants import UIError
from . import observe

_owner = None
_generation = None
_scene = None
_modal_baseline = {}
_unsettled = False


def _has_modal():
    return any(w.mixar_ui_modal_count() > _modal_baseline.get(w.as_pointer(), 0)
               for w in bpy.context.window_manager.windows)


def active():
    global _unsettled, _owner, _generation
    if _owner is not None and bpy.context.window_manager.mixar_ui_generation() != _generation:
        _unsettled = _has_modal()
        _owner, _generation = None, None
    if _unsettled and not _has_modal():
        _unsettled = False
    return _owner is not None or _unsettled


def available():
    from mixar.modules.common.render_coordinator.core import busy
    from mixar.modules.space_mixie_chat.core.session import SessionManager as session
    from mixar.modules.space_mixie_chat.constants import SessionState
    if busy():
        raise UIError("render_in_progress", "Wait for the render to finish")
    if bpy.context.window_manager.mixar_window_resizing:
        raise UIError("ui_busy", "Wait for window resize to finish")
    scene = observe.main_window().scene
    if session.run_open(scene) or session.get_state(scene) != SessionState.IDLE:
        raise UIError("scene_busy", "Wait for the active scene operation to finish")


def prepare(owner):
    available()
    active()  # Clear Python ownership after native takeover/expiry.
    if _owner is not None and _owner != owner:
        raise UIError("ui_busy", "Another connection owns Mixar input")
    wm = bpy.context.window_manager
    if _owner is None and not _unsettled and any(getattr(w, "modal_operators", ()) for w in wm.windows):
        raise UIError("ui_busy", "Finish the current modal operation before starting UI control")


def settling():
    """Scene completion precedes removal of its viewport-lock modal by a tick."""
    try:
        available()
    except UIError:
        return False
    return any(getattr(op, "bl_idname", "") in {
        "mixar.agent_viewport_block", "MIXAR_OT_agent_viewport_block"}
        for w in bpy.context.window_manager.windows for op in getattr(w, "modal_operators", ()))


def begin(owner):
    global _owner, _generation, _scene, _modal_baseline, _unsettled
    prepare(owner)
    wm = bpy.context.window_manager
    if not wm.mixar_ui_begin(owner=owner):
        raise UIError("ui_busy", "Mixar input is unavailable")
    if _owner is None and not _unsettled:
        _modal_baseline = {w.as_pointer(): w.mixar_ui_modal_count() for w in wm.windows}
    _unsettled = False
    _owner, _generation = owner, wm.mixar_ui_generation()
    _scene = observe.main_window().scene.as_pointer()


def check(owner):
    if (_owner != owner or bpy.context.window_manager.mixar_ui_generation() != _generation):
        raise UIError("control_revoked", "User input or a context change interrupted UI control")
    if observe.main_window().scene.as_pointer() != _scene:
        raise UIError("context_changed", "The active scene changed during UI input")
    available()


def release(owner=None, *, require_settled=False):
    global _owner, _generation, _unsettled
    active()
    if require_settled and _unsettled:
        raise UIError("modal_active", "Finish or cancel the interrupted UI operation before running a scene tool")
    if _owner is not None and (owner is None or owner == _owner):
        if require_settled and _has_modal():
            raise UIError("modal_active", "Finish or cancel the current UI operation before running a scene tool")
        _unsettled = _has_modal()
        bpy.context.window_manager.mixar_ui_end(owner=_owner)
        _owner, _generation = None, None


def forget():
    """Shutdown after Blender's data has been freed: no RNA access."""
    global _owner, _generation, _unsettled
    _owner, _generation = None, None
    _unsettled = False
