# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Shared node template and board action menus."""

from bpy.types import Menu

from ...core.canvas_context import has_moodboard_content
from ...core.node_templates import available_templates
from ..canvas_template_helpers import draw_template


class MIXIE_MT_node_templates(Menu):
    """Start with an editable node template"""

    bl_idname = "MIXIE_MT_node_templates"
    bl_label = "Node Templates"
    bl_options = {'SEARCH_ON_KEY_PRESS'}

    def draw(self, context):
        layout = self.layout.mixar_surface(theme='ZEN', density='COMPACT')
        layout.operator_context = 'INVOKE_DEFAULT'
        items = available_templates()
        for item in items:
            draw_template(layout, item)
        if not any(item[3] for item in items):
            layout.separator()
            layout.label(text="Connect to load generation models", icon='INFO')


class MIXIE_MT_canvas_board(Menu):
    """Arrange, frame, or clear the board"""

    bl_idname = "MIXIE_MT_canvas_board"
    bl_label = "Board"

    def draw(self, context):
        layout = self.layout.mixar_surface(theme='ZEN', density='COMPACT')
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.operator("mixie.moodboard_frame", text="Frame All", icon='HOME')
        layout.menu("MIXIE_MT_moodboard_arrange", icon='NODETREE')
        layout.separator()
        row = layout.row()
        row.enabled = has_moodboard_content(context)
        row.operator("mixie.clear_moodboard", text="Clear Board", icon='TRASH')
        row.mixar_style(component='ACTION', variant='DANGER')


classes = (MIXIE_MT_node_templates, MIXIE_MT_canvas_board)
