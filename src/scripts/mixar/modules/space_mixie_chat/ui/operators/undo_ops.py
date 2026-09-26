# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Undo and redo are held while an agent works in ANY scene tab.

Blender's undo is document-wide: a step taken back in the visible, idle tab
also takes back what another tab's agent just built — or the other tab
itself, when its creation is the newest step (found by the parallel-scenes
stress run: an undo in the home tab deleted the tab whose agent was mid-turn,
stranding its backend turn). The visible tab's own turn is already behind the
viewport lock; this covers the other tabs. The guard is bound ahead of the
stock undo/redo keys (addon keyconfig, `scene_tabs_keymap.py`) and passes the
key through when nothing is working.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator

from mixar.modules.common.scenes_log import slog

from ...constants import SessionState
from ...core.session import get_session_manager

_ACTIVE = (SessionState.BUSY, SessionState.MODIFYING, SessionState.AWAITING_INPUT)


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


def guard(redo: bool, report) -> set:
    """The operator's decision: pass the key through, or refuse with a report."""
    busy = working_tabs()
    if not busy:
        return {'PASS_THROUGH'}   # the stock ed.undo / ed.redo binding runs
    what = "Redo" if redo else "Undo"
    shown = ", ".join(busy[:3]) + (" …" if len(busy) > 3 else "")
    report({'WARNING'}, f"{what} is unavailable while an agent works in {shown}")
    slog("undo.refused", None, redo=bool(redo), tabs=busy)
    return {'CANCELLED'}


class MIXIE_CHAT_OT_guarded_undo(Operator):
    """Undo / redo, unless an agent is working in a scene tab"""

    bl_idname = "mixie_chat.guarded_undo"
    bl_label = "Undo (agent-aware)"
    bl_options = {'INTERNAL'}

    redo: BoolProperty(name="Redo", default=False, options={'SKIP_SAVE'})

    def execute(self, context):
        return guard(bool(self.redo), self.report)


classes = (MIXIE_CHAT_OT_guarded_undo,)
