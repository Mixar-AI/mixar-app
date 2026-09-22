# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""One set of canvas controls, hosted by both native moodboard regions."""

from bpy.types import Panel

from ...constants import NODE_TEMPLATES
from ...core.canvas_context import is_moodboard_context
from ...core.node_templates import available_templates
from ..canvas_template_helpers import draw_template

_MESH_TEMPLATE = next(item for item in NODE_TEMPLATES if item[0] == 'MESH_REFERENCE')


def _more_templates(row):
    more = row.row()
    more.ui_units_x = 1.6
    more.menu("MIXIE_MT_node_templates", text="", icon='ADD')
    more.mixar_style(component='ACTION', variant='SECONDARY')


class _CanvasPanel:
    bl_label = ""
    bl_space_type = 'MIXIE'
    bl_region_type = 'WINDOW'
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        return is_moodboard_context(context)


class MIXIE_PT_canvas_tools(_CanvasPanel, Panel):
    bl_idname = "MIXIE_PT_canvas_tools"

    def draw(self, context):
        from ..moodboard_toolbar import draw_moodboard_add_tools

        draw_moodboard_add_tools(self.layout, context)


class MIXIE_PT_canvas_templates(_CanvasPanel, Panel):
    bl_idname = "MIXIE_PT_canvas_templates"

    def draw(self, context):
        surface = self.layout.mixar_surface(theme='ZEN', density='COMPACT')
        surface.operator_context = 'INVOKE_DEFAULT'
        row = surface.row()
        row.scale_y = 1.6
        draw_template(row, _MESH_TEMPLATE)
        for item in available_templates():
            if item[0] not in {entry[0] for entry in NODE_TEMPLATES[:3]}:
                continue
            draw_template(row, item)
        _more_templates(row)


class _CompactTemplates(_CanvasPanel):
    show_mesh = True

    def draw(self, context):
        surface = self.layout.mixar_surface(theme='ZEN', density='COMPACT')
        surface.operator_context = 'INVOKE_DEFAULT'
        row = surface.row()
        row.scale_y = 1.6
        if self.show_mesh:
            draw_template(row, _MESH_TEMPLATE)
        _more_templates(row)


class MIXIE_PT_canvas_templates_compact(_CompactTemplates, Panel):
    bl_idname = "MIXIE_PT_canvas_templates_compact"


class MIXIE_PT_canvas_templates_icon(_CompactTemplates, Panel):
    bl_idname = "MIXIE_PT_canvas_templates_icon"
    show_mesh = False


classes = (
    MIXIE_PT_canvas_tools,
    MIXIE_PT_canvas_templates, MIXIE_PT_canvas_templates_compact,
    MIXIE_PT_canvas_templates_icon,
)
