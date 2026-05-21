# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Toggle the chat history pane open / closed.

Why a click-toggle and not a press-and-hold drag: Blender Python UI
buttons fire on RELEASE, not PRESS. By the time an operator's invoke
runs, the user has already let go of the mouse — there's no way to
intercept the press itself. So press-and-hold drag from a Python
button is genuinely impossible without a custom C++ button type
(major surgery on Blender's UI internals).

Sliders DO have native press-and-hold drag, but they always show
their numeric value in the bar — which the user explicitly rejected.

So: click toggles. Two states (collapsed / expanded). Reliable,
predictable, and what we ship.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

_logger = get_logger(__name__)

# How many history rows to show when the pane is open. The popup
# auto-grows to fit; this is a comfortable default that fits a few
# messages on screen without dominating the viewport.
_OPEN_LINES = 12


class MIXAR_OT_agent_bubble_drag_history(Operator):
    """Toggle the chat history pane open or closed"""

    bl_idname = "mixar.agent_bubble_drag_history"
    bl_label = "Toggle Agent Bubble History"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        scene = context.scene
        if scene is None:
            return {"CANCELLED"}
        current = getattr(scene, "mixar_bubble_history_lines", 0)
        scene.mixar_bubble_history_lines = 0 if current > 0 else _OPEN_LINES
        # Tag every viewport so the popup re-renders right away.
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
        return {"FINISHED"}


classes = (MIXAR_OT_agent_bubble_drag_history,)
