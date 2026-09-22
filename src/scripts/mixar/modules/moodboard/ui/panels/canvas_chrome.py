# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""One set of canvas controls, hosted by both native moodboard regions."""

from math import ceil

import blf
from bpy.app.translations import pgettext_iface
from bpy.types import Panel

from ...core.canvas_context import is_moodboard_context
from ...core.canvas_template_fit import canvas_template_strip_items, templates_that_fit
from ...core.node_templates import available_templates
from ..canvas_template_helpers import draw_template


def _ui_scale(context) -> float:
    try:
        return float(context.preferences.system.ui_scale) or 1.0
    except Exception:
        return 1.0


def _more_templates(row):
    more = row.column()
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
        row.alignment = 'LEFT'
        row.scale_y = 1.6
        available = context.moodboard_chrome_width
        scale = _ui_scale(context)
        widget_unit = context.moodboard_chrome_widget_unit
        font = context.moodboard_chrome_font
        # Match the native Action painter (mixar/components.cc): Body type,
        # default-density inset/icon metrics, and its native-layout unit.
        unit = .65 * scale
        blf.size(font, 18 * unit)
        items = canvas_template_strip_items(available_templates())
        widths = {
            item[0]: ceil(blf.dimensions(font, pgettext_iface(item[1]))[0]
                          + (2 * 20 + 18 + 8) * unit) + 2
            for item in items
        }
        for item in templates_that_fit(
            available, items, widths=widths, more_width=int(1.6 * widget_unit),
            gap=context.moodboard_chrome_gap,
        ):
            draw_template(row, item, width_units=widths[item[0]] / widget_unit)
        _more_templates(row)


classes = (
    MIXIE_PT_canvas_tools,
    MIXIE_PT_canvas_templates,
)
