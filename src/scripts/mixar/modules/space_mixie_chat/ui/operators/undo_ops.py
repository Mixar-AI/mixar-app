# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Undo and redo are held while an agent works in ANY scene tab.

Blender's undo is document-wide: a step taken back in the visible, idle tab
also takes back what another tab's agent just built — or the other tab
itself, when its creation is the newest step (found by the parallel-scenes
stress run: an undo in the home tab deleted the tab whose agent was mid-turn,
stranding its backend turn). The visible tab's own turn is already behind the
viewport lock; this covers the other tabs.

A keymap item cannot do it (the stock Screen binding runs first), so a
window-level modal — the same shape as the viewport lock, started by a light
timer tick while any tab works and gone when none does — consumes the undo /
redo chords with a warning and passes every other event through.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.scenes_log import slog

from ...constants import SessionState
from ...core.session import get_session_manager

logger = get_logger(__name__)

_ACTIVE = (SessionState.BUSY, SessionState.MODIFYING, SessionState.AWAITING_INPUT)
_TICK_S = 0.5
_running = False


def working_tabs() -> list:
    """Names of the user's tabs whose agent is mid-turn or holds an open run."""
    from .scene_tab_ops import real_scenes

    session = get_session_manager()
    names = []
    for scene in real_scenes():
        try:
            if session.get_state(scene) in _ACTIVE or session.run_open(scene):
                names.append(scene.name)
        except Exception:  # noqa: BLE001 — a scene mid-teardown
            continue
    return names


def is_undo_chord(event) -> bool:
    """Ctrl+Z / Cmd+Z and their Shift (redo) variants, on the press."""
    return (getattr(event, "type", "") == 'Z' and getattr(event, "value", "") == 'PRESS'
            and (bool(getattr(event, "ctrl", False)) or bool(getattr(event, "oskey", False)))
            and not getattr(event, "alt", False))


def refuse(redo: bool, report, busy: list) -> None:
    what = "Redo" if redo else "Undo"
    shown = ", ".join(busy[:3]) + (" …" if len(busy) > 3 else "")
    report({'WARNING'}, f"{what} is unavailable while an agent works in {shown}")
    slog("undo.refused", None, redo=bool(redo), tabs=busy)


class MIXIE_CHAT_OT_undo_shield(Operator):
    """Hold undo and redo while an agent works in a scene tab"""

    bl_idname = "mixie_chat.undo_shield"
    bl_label = "Undo Shield"
    bl_options = {'INTERNAL'}

    _timer = None

    def invoke(self, context, event):
        global _running
        if _running or not working_tabs():
            return {'CANCELLED'}
        wm = context.window_manager
        self._timer = wm.event_timer_add(_TICK_S, window=context.window)
        wm.modal_handler_add(self)
        _running = True
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'TIMER':
            if not working_tabs():
                self._finish(context)
                return {'FINISHED'}
            return {'PASS_THROUGH'}
        if is_undo_chord(event):
            busy = working_tabs()
            if busy:
                refuse(bool(event.shift), self.report, busy)
                return {'RUNNING_MODAL'}   # consumed: the stock undo never sees it
        return {'PASS_THROUGH'}

    def cancel(self, context):
        self._finish(context)

    def _finish(self, context):
        global _running
        try:
            if self._timer is not None:
                context.window_manager.event_timer_remove(self._timer)
        except Exception:  # noqa: BLE001
            pass
        self._timer = None
        _running = False


def _shield_alive() -> bool:
    for wm in bpy.data.window_managers:
        for win in wm.windows:
            try:
                if win.modal_operators.get('MIXIE_CHAT_OT_undo_shield') is not None:
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


def _shield_tick():
    """Timer: start the shield whenever a tab is working and none is up.
    A modal never survives a file load; the window list is the truth."""
    global _running
    try:
        if _running and not _shield_alive():
            _running = False
        if _running or not working_tabs():
            return _TICK_S
        wm = bpy.context.window_manager
        win = next((w for w in wm.windows if w.screen and any(a.type == 'VIEW_3D' for a in w.screen.areas)),
                   wm.windows[0] if wm.windows else None)
        if win is None:
            return _TICK_S
        with bpy.context.temp_override(window=win):
            bpy.ops.mixie_chat.undo_shield('INVOKE_DEFAULT')
    except Exception as exc:  # noqa: BLE001 — never break the tick
        logger.debug("undo shield tick: %s", exc)
    return _TICK_S


def ensure_shield_timer() -> None:
    try:
        if not bpy.app.timers.is_registered(_shield_tick):
            bpy.app.timers.register(_shield_tick, first_interval=_TICK_S, persistent=True)
    except Exception:  # noqa: BLE001
        logger.debug("undo shield timer not registered", exc_info=True)


def stop_shield_timer() -> None:
    try:
        if bpy.app.timers.is_registered(_shield_tick):
            bpy.app.timers.unregister(_shield_tick)
    except Exception:  # noqa: BLE001
        pass


classes = (MIXIE_CHAT_OT_undo_shield,)
