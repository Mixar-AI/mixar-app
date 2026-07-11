# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent run-state probe for the viewport lock.

Single source of truth for "is the agent actively executing a turn?"
— used by both the halo renderer (what to draw) and the input-block
modal (when to consume clicks). Reads ``scene.mixie_chat_state`` (the
same enum the agent bubble status pill uses) plus
``scene.mixie_chat_active_turn_mode`` (the mode the running turn was
started in).
"""

from __future__ import annotations

import bpy

# Session states where the agent is actively running/editing the scene.
# Deliberately excludes AWAITING_INPUT (the agent has paused for the
# user) and IDLE/CONNECTING/OFFLINE.
_EXECUTING_STATES = {"BUSY", "MODIFYING"}


def is_agent_executing(scene=None) -> bool:
    """True when an AGENT-mode turn is mid-execution on the given
    scene (or the context scene if none passed). Never raises.

    Gated on ``mixie_chat_active_turn_mode == 'AGENT'`` — the mode the
    RUNNING turn was started in, stamped by ``SessionManager.set_state``
    — NOT the live ``mixie_chat_mode`` dropdown. The dropdown stays
    editable mid-turn, so keying off it let a mid-run flip to Ask (and
    back) drop the halo + input block while the agent was still editing
    the scene, letting the user select objects out from under it. The
    lock only applies to autonomous agent runs — not Ask (Q&A) or
    Generate (image/3D generation) turns, which also go BUSY but don't
    edit the viewport.
    """
    try:
        if scene is None:
            scene = bpy.context.scene
        if scene is None:
            return False
        if (getattr(scene, "mixie_chat_active_turn_mode", "") or "") != "AGENT":
            return False
        state = getattr(scene, "mixie_chat_state", "") or ""
        return state in _EXECUTING_STATES
    except Exception:
        return False
