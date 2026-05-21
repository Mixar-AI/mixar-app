# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vertex color editor UI panels.

This module contains the UI panel classes and draw functions for the
vertex color editor interface.
"""

import bpy

from ...core.element.get_elements import get_active_vertex_color
from ...core.node.node_utils import get_vertex_colors
from ...utils.blender_commons import get_user_preferences


def vcol_editor_draw(self, context):
    """Draws the vertex color editor UI panel.

    Creates the UI layout for the vertex color editor, including vertex color
    list display/toggle, fill operations with preset colors, and custom color
    selection.

    Args:
        self: The panel instance.
        context (bpy.types.Context): The current Blender context.

    Returns:
        None
    """
    obj = context.object
    mesh = obj.data
    ve = context.scene.ve_edit

    col = self.layout.column()
    vcols = get_vertex_colors(obj)
    vcol = get_active_vertex_color(obj)

    row = col.row(align=True)

    if not ve.show_vcol_list:
        row.prop(ve, 'show_vcol_list', text='', emboss=False, icon='TRIA_RIGHT')
        if vcol:
            row.label(text='Active: ' + vcol.name)
        else:
            row.label(text='Active: -')
    else:
        row.prop(ve, 'show_vcol_list', text='', emboss=False, icon='TRIA_DOWN')
        row.label(text='Vertex Colors')

        row = col.row()
        rcol = row.column()
        rcol.template_list("MESH_UL_color_attributes", "vcols", mesh,
                           "color_attributes", vcols, "active_color_index", rows=2)
        rcol = row.column(align=True)
        rcol.operator("geometry.color_attribute_add", icon='ADD', text="")
        rcol.operator("geometry.color_attribute_remove", icon='REMOVE', text="")

    col.separator()

    ccol = col.column(align=True)
    ccol.operator("mesh.y_vcol_fill", icon='BRUSH_DATA', text='Fill with White').color_option = 'WHITE'
    ccol.operator("mesh.y_vcol_fill", icon='BRUSH_DATA', text='Fill with Black').color_option = 'BLACK'

    col.separator()
    ccol = col.column(align=True)
    ccol.operator("mesh.y_vcol_fill", icon='BRUSH_DATA', text='Fill with Color').color_option = 'CUSTOM'

    ccol.prop(ve, "color", text="")


class VIEW3D_PT_y_vcol_editor_ui(bpy.types.Panel):
    """Vertex color editor panel in the UI region."""

    bl_space_type = 'VIEW_3D'
    bl_label = "Vertex Color Editor"
    bl_context = "mesh_edit"
    bl_region_type = 'UI'
    bl_category = 'VCol Edit'

    @classmethod
    def poll(cls, context):
        mpup = get_user_preferences()
        return mpup and (not hasattr(mpup, 'show_experimental') or mpup.show_experimental) and context.object and context.object.type == 'MESH'

    def draw(self, context):
        vcol_editor_draw(self, context)


class VIEW3D_PT_y_vcol_editor_tools(bpy.types.Panel):
    """Vertex color editor panel in the Tools region."""

    bl_space_type = 'VIEW_3D'
    bl_label = "Vertex Color Editor"
    bl_context = "mesh_edit"
    bl_region_type = 'TOOLS'

    @classmethod
    def poll(cls, context):
        mpup = get_user_preferences()
        return mpup and (not hasattr(mpup, 'show_experimental') or mpup.show_experimental) and context.object and context.object.type == 'MESH'

    def draw(self, context):
        vcol_editor_draw(self, context)
