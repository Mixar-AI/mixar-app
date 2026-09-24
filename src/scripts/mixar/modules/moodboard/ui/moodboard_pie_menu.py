# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Pie Menu

Pie menu for the same catalog-backed nodes as the canvas Add menu (Ctrl+Tab).
"""

import bpy
from bpy.types import Menu, Operator


from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE
from mixar.modules.moodboard.core.canvas_context import is_moodboard_context
from mixar.modules.moodboard.core.node_templates import available_templates
from .canvas_template_helpers import draw_template


class MIXIE_MT_moodboard_pie_menu(Menu):
    """Pie menu for moodboard features"""
    bl_idname = "MIXIE_MT_moodboard_pie_menu"
    bl_label = "Moodboard Features"

    def draw(self, context):
        layout = self.layout.mixar_surface(theme='ZEN', density='COMPACT')
        pie = layout.menu_pie()
        # Preserve the originating drawer instead of substituting View3D WINDOW.
        pie.operator_context = 'INVOKE_DEFAULT'
        items = available_templates()
        # Blender has eight radial slots. Keep every Add entry directly
        # reachable: the last slot is a column when the catalog offers more.
        for item in items[:7]:
            draw_template(pie, item)
        if len(items) > 7:
            overflow = pie.column()
            for item in items[7:]:
                draw_template(overflow, item)
        else:
            for _ in range(8 - len(items)):
                pie.separator()


class MIXIE_OT_moodboard_pie_menu_call(Operator):
    """Call the moodboard pie menu"""
    bl_idname = "mixie.moodboard_pie_menu_call"
    bl_label = "Moodboard Pie Menu"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return is_moodboard_context(context)

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="MIXIE_MT_moodboard_pie_menu")
        return {'FINISHED'}


# Only include classes if MIXIE space is available
classes = (
    MIXIE_MT_moodboard_pie_menu,
    MIXIE_OT_moodboard_pie_menu_call,
) if MIXIE_SPACE_AVAILABLE else ()
