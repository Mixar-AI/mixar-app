# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Selection Operators

Operators for UV selection tools in the Mixar UV Editor.
"""

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty, FloatProperty

from mixar.modules.uv_editor.common.uv_utils import (
    get_mixar_uv_image_editor,
    poll_mixar_uv_mode,
    with_uv_context,
)


# ============================================================
# Select Similar — dynamic Type items (mirror native uv.select_similar)
# ============================================================

def _select_similar_items(_self, context):
    """Return Type enum items appropriate for the active UV select mode.

    Mirrors Blender's native `uv.select_similar` mode-aware filtering so
    the operator's redo panel only shows valid options. The returned
    list is cached on this function to keep it alive — Blender requires
    Python to retain the reference for dynamic enum items.
    """
    items = None
    ts = context.tool_settings if context else None
    if ts is None:
        items = [
            ('AREA', "Area", "Face area in UV space"),
            ('AREA_3D', "Area 3D", "Face area in 3D space"),
            ('MATERIAL', "Material", "Select by material"),
            ('OBJECT', "Object", "Select by object"),
            ('SIDES', "Sides", "Polygon sides"),
            ('WINDING', "Winding", "Face winding direction"),
        ]
    elif ts.use_uv_select_island:
        items = [
            ('AREA', "Area", "Island area in UV space"),
            ('AREA_3D', "Area 3D", "Island area in 3D space"),
            ('FACE', "Faces in Island", "Number of faces in island"),
        ]
    else:
        if ts.use_uv_select_sync:
            is_v, is_e, is_f = ts.mesh_select_mode
        else:
            mode = ts.uv_select_mode
            is_v = mode == 'VERTEX'
            is_e = mode == 'EDGE'
            is_f = mode == 'FACE'

        if is_f:
            items = [
                ('AREA', "Area", "Face area in UV space"),
                ('AREA_3D', "Area 3D", "Face area in 3D space"),
                ('MATERIAL', "Material", "Select by material"),
                ('OBJECT', "Object", "Select by object"),
                ('SIDES', "Sides", "Polygon sides"),
                ('WINDING', "Winding", "Face winding direction"),
            ]
        elif is_e:
            items = [
                ('LENGTH', "Length", "Edge length in UV space"),
                ('LENGTH_3D', "Length 3D", "Edge length in 3D space"),
                ('PIN', "Pin", "Select by pin state"),
            ]
        else:
            items = [
                ('PIN', "Pin", "Select by pin state"),
            ]

    _select_similar_items.cache = items
    return items


_select_similar_items.cache = []


class MIXAR_OT_activate_box_select(Operator):
    """Activate Box Select tool in UV Editor"""
    bl_idname = "mixar.activate_box_select"
    bl_label = "Activate Box Select"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.wm.tool_set_by_id(name='builtin.select_box')
        return {'FINISHED'}


class MIXAR_OT_activate_circle_select(Operator):
    """Activate Circle Select tool in UV Editor"""
    bl_idname = "mixar.activate_circle_select"
    bl_label = "Activate Circle Select"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.wm.tool_set_by_id(name='builtin.select_circle')
        return {'FINISHED'}


class MIXAR_OT_activate_lasso_select(Operator):
    """Activate Lasso Select tool in UV Editor"""
    bl_idname = "mixar.activate_lasso_select"
    bl_label = "Activate Lasso Select"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.wm.tool_set_by_id(name='builtin.select_lasso')
        return {'FINISHED'}


class MIXAR_OT_select_more(Operator):
    """Expand UV selection"""
    bl_idname = "mixar.select_more"
    bl_label = "Select More"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.select_more()
        return {'FINISHED'}


class MIXAR_OT_select_less(Operator):
    """Contract UV selection"""
    bl_idname = "mixar.select_less"
    bl_label = "Select Less"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.select_less()
        return {'FINISHED'}


class MIXAR_OT_shortest_path_select(Operator):
    """Select shortest path between UVs"""
    bl_idname = "mixar.shortest_path_select"
    bl_label = "Shortest Path"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.shortest_path_select()
        return {'FINISHED'}


class MIXAR_OT_select_similar(Operator):
    """Select similar UVs by property type"""
    bl_idname = "mixar.select_similar"
    bl_label = "Select Similar"
    bl_options = {'REGISTER', 'UNDO'}

    type: EnumProperty(
        name="Type",
        description="Property to compare against",
        items=_select_similar_items,
    )
    compare: EnumProperty(
        name="Compare",
        description="How values are compared against the active selection",
        items=[
            ('EQUAL', "Equal", ""),
            ('GREATER', "Greater", ""),
            ('LESS', "Less", ""),
        ],
        default='EQUAL',
    )
    threshold: FloatProperty(
        name="Threshold",
        description="Tolerance when comparing values",
        default=0.0,
        min=0.0,
        soft_max=1.0,
    )

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.uv.select_similar(
                type=self.type,
                compare=self.compare,
                threshold=self.threshold,
            )
        return {'FINISHED'}


class MIXAR_OT_select_linked(Operator):
    """Select linked UVs"""
    bl_idname = "mixar.select_linked"
    bl_label = "Select Linked"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area, space_data=area.spaces.active):
            bpy.ops.uv.select_linked()
        return {'FINISHED'}


classes = (
    MIXAR_OT_activate_box_select,
    MIXAR_OT_activate_circle_select,
    MIXAR_OT_activate_lasso_select,
    MIXAR_OT_select_more,
    MIXAR_OT_select_less,
    MIXAR_OT_shortest_path_select,
    MIXAR_OT_select_similar,
    MIXAR_OT_select_linked,
)
