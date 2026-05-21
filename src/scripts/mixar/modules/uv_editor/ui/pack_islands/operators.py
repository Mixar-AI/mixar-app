# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Pack Islands Operators

Operators for UV pack islands operations in the Mixar UV Editor.
"""

import bpy
from bpy.types import Operator

from mixar.modules.uv_editor.common.uv_utils import (
    poll_mixar_uv_edit_mode,
    with_uv_context,
    with_uv_context_and_region,
    get_operator_properties,
)


class MIXAR_OT_pack_islands(Operator):
    """Pack UV islands using stored properties (no popup)"""
    bl_idname = "mixar.pack_islands"
    bl_label = "Pack Islands"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        op_props = get_operator_properties(context, "uv.pack_islands")
        with context.temp_override(area=area):
            bpy.ops.uv.pack_islands(
                'EXEC_DEFAULT',
                shape_method=op_props.shape_method,
                scale=op_props.scale,
                rotate=op_props.rotate,
                rotate_method=op_props.rotate_method,
                margin_method=op_props.margin_method,
                margin=op_props.margin,
                pin=op_props.pin,
                pin_method=op_props.pin_method,
                merge_overlap=op_props.merge_overlap,
                udim_source=op_props.udim_source,
            )
        return {'FINISHED'}


class MIXAR_OT_average_islands_scale(Operator):
    """Average the size of UV islands"""
    bl_idname = "mixar.average_islands_scale"
    bl_label = "Average Islands Scale"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        op_props = get_operator_properties(context, "uv.average_islands_scale")
        with context.temp_override(area=area):
            bpy.ops.uv.average_islands_scale(
                scale_uv=op_props.scale_uv,
                shear=op_props.shear,
            )
        return {'FINISHED'}


class MIXAR_OT_minimize_stretch(Operator):
    """Minimize UV stretch by relaxing islands"""
    bl_idname = "mixar.minimize_stretch"
    bl_label = "Minimize Stretch"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        op_props = get_operator_properties(context, "uv.minimize_stretch")
        with context.temp_override(area=area):
            bpy.ops.uv.minimize_stretch(
                fill_holes=op_props.fill_holes,
                blend=op_props.blend,
                iterations=op_props.iterations
            )
        return {'FINISHED'}


class MIXAR_OT_custom_region_set(Operator):
    """Create custom regions in UV space for packing"""
    bl_idname = "mixar.custom_region_set"
    bl_label = "Set Custom Region"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        with context.temp_override(area=area, region=region):
            # Use INVOKE_DEFAULT to allow interactive selection in UV editor
            bpy.ops.uv.custom_region_set('INVOKE_DEFAULT')
        return {'FINISHED'}


classes = (
    MIXAR_OT_pack_islands,
    MIXAR_OT_average_islands_scale,
    MIXAR_OT_minimize_stretch,
    MIXAR_OT_custom_region_set,
)
