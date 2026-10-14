# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Session-only position of the island's attached reference column."""
import bpy
from bpy.props import FloatProperty


def _redraw(_self, context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'AGENT_BUBBLE':
                area.tag_redraw()


def register():
    bpy.types.WindowManager.mixar_reference_scroll = FloatProperty(
        name="Reference scroll position", default=0, min=0, max=1,
        options={'SKIP_SAVE'}, update=_redraw,
    )


def unregister():
    if hasattr(bpy.types.WindowManager, "mixar_reference_scroll"):
        del bpy.types.WindowManager.mixar_reference_scroll
