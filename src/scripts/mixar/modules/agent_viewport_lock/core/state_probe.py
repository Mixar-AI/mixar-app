# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent run-state probe for the viewport lock.

Single source of truth for "is the agent actively executing a turn?"
— used by both the halo renderer (what to draw) and the input-block
modal (when to consume clicks). Reads ``scene.mixie_chat_state``,
the same enum the agent bubble status pill uses.
"""

from __future__ import annotations

import bpy

# Session states where the agent is actively running/editing the scene.
# Deliberately excludes AWAITING_INPUT (the agent has paused for the
# user) and IDLE/CONNECTING/OFFLINE.
_EXECUTING_STATES = {"BUSY", "MODIFYING"}


def is_agent_executing(scene=None) -> bool:
    """True when the AGENT-mode agent is mid-execution on the given
    scene (or the context scene if none passed). Never raises.

    Gated on ``mixie_chat_mode == 'AGENT'`` so the halo + input lock
    only appear for autonomous agent runs — not for Ask (Q&A) or
    Generate (image/3D generation) turns, which also go BUSY but don't
    edit the viewport out from under the user.
    """
    try:
        if scene is None:
            scene = bpy.context.scene
        if scene is None:
            return False
        if (getattr(scene, "mixie_chat_mode", "") or "") != "AGENT":
            return False
        state = getattr(scene, "mixie_chat_state", "") or ""
        return state in _EXECUTING_STATES
    except Exception:
        return False
