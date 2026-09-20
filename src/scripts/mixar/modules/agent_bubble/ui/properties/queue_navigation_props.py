# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Session-only island Queue position; independent of selected job and chat."""
import bpy
from bpy.props import FloatProperty


def _redraw(_self, context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'AGENT_BUBBLE':
                area.tag_redraw()
                for region in area.regions:
                    region.tag_redraw()


def register():
    bpy.types.WindowManager.mixar_queue_offset = FloatProperty(
        name="Queue scroll position", default=0, min=0, max=1_000_000_000,
        options={'SKIP_SAVE'}, update=_redraw,
    )


def unregister():
    if hasattr(bpy.types.WindowManager, "mixar_queue_offset"):
        del bpy.types.WindowManager.mixar_queue_offset
