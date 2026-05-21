# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Transform Operators

Operators for UV transformation in the Mixar UV Editor.
"""

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty

from mixar.modules.uv_editor.common.uv_utils import (
    poll_mixar_uv_mode,
    poll_mixar_uv_edit_mode,
    with_uv_context,
    with_uv_context_and_region,
    get_operator_properties,
)


class MIXAR_OT_snap_selected(Operator):
    """Snap selected UVs"""
    bl_idname = "mixar.snap_selected"
    bl_label = "Snap Selected"
    bl_options = {'REGISTER', 'UNDO'}

    target: EnumProperty(
        name="Target",
        items=[
            ('PIXELS', "Pixels", ""),
            ('CURSOR', "Cursor", ""),
            ('CURSOR_OFFSET', "Cursor (Offset)", ""),
            ('ADJACENT_UNSELECTED', "Adjacent Unselected", ""),
        ],
        default='PIXELS'
    )

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.snap_selected(target=self.target)
        return {'FINISHED'}


class MIXAR_OT_snap_cursor(Operator):
    """Snap 2D cursor"""
    bl_idname = "mixar.snap_cursor"
    bl_label = "Snap Cursor"
    bl_options = {'REGISTER', 'UNDO'}

    target: EnumProperty(
        name="Target",
        items=[
            ('PIXELS', "Pixels", ""),
            ('SELECTED', "Selected", ""),
            ('ORIGIN', "Origin", ""),
        ],
        default='PIXELS'
    )

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.snap_cursor(target=self.target)
        return {'FINISHED'}


class MIXAR_OT_mirror(Operator):
    """Mirror selected UVs"""
    bl_idname = "mixar.mirror"
    bl_label = "Mirror"
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(
        name="Axis",
        items=[
            ('X', "X", "Mirror on X axis"),
            ('Y', "Y", "Mirror on Y axis"),
        ],
        default='X'
    )

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        with context.temp_override(area=area, region=region):
            if self.axis == 'X':
                bpy.ops.transform.mirror(constraint_axis=(True, False, False))
            else:
                bpy.ops.transform.mirror(constraint_axis=(False, True, False))
        return {'FINISHED'}


class MIXAR_OT_align(Operator):
    """Align selected UVs"""
    bl_idname = "mixar.align"
    bl_label = "Align"
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(
        name="Axis",
        items=[
            ('ALIGN_S', "Straighten", ""),
            ('ALIGN_T', "Straighten X", ""),
            ('ALIGN_U', "Straighten Y", ""),
            ('ALIGN_AUTO', "Align Auto", ""),
            ('ALIGN_X', "Align X", ""),
            ('ALIGN_Y', "Align Y", ""),
        ],
        default='ALIGN_AUTO'
    )

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.align(axis=self.axis)
        return {'FINISHED'}


class MIXAR_OT_align_rotation(Operator):
    """Align island rotation"""
    bl_idname = "mixar.align_rotation"
    bl_label = "Align Rotation"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        # Get properties from last operator execution
        op_props = get_operator_properties(context, "uv.align_rotation")
        with context.temp_override(area=area):
            bpy.ops.uv.align_rotation(
                method=op_props.method,
                axis=op_props.axis,
                correct_aspect=op_props.correct_aspect
            )
        return {'FINISHED'}


class MIXAR_OT_move_on_axis(Operator):
    """Move UVs on axis (Dynamic, Pixel, or UDIM)"""
    bl_idname = "mixar.move_on_axis"
    bl_label = "Move on Axis"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        # Get properties from last operator execution (shown in UV Properties panel)
        # The C++ code updates these properties with the current distance before calling this operator
        op_props = get_operator_properties(context, "uv.move_on_axis")
        with context.temp_override(area=area):
            bpy.ops.uv.move_on_axis(
                type=op_props.type,
                axis=op_props.axis,
                distance=op_props.distance
            )
        return {'FINISHED'}


class MIXAR_OT_arrange_islands(Operator):
    """Arrange UV islands"""
    bl_idname = "mixar.arrange_islands"
    bl_label = "Arrange Islands"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        # Get properties from last operator execution (shown in UV Properties panel)
        op_props = get_operator_properties(context, "uv.arrange_islands")
        with context.temp_override(area=area):
            bpy.ops.uv.arrange_islands(
                initial_position=op_props.initial_position,
                axis=op_props.axis,
                align=op_props.align,
                order=op_props.order,
                margin=op_props.margin
            )
        return {'FINISHED'}


class MIXAR_OT_uv_translate(Operator):
    """Apply translate transformation to selected UVs"""
    bl_idname = "mixar.uv_translate"
    bl_label = "Apply Move"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        # Get the transform values
        op_props = get_operator_properties(context, "transform.translate")
        with context.temp_override(area=area, region=region, space_data=area.spaces.active):
            bpy.ops.transform.translate(
                value=op_props.value,
                orient_type='GLOBAL',
                constraint_axis=(False, False, False)
            )
        return {'FINISHED'}


class MIXAR_OT_uv_rotate(Operator):
    """Apply rotate transformation to selected UVs"""
    bl_idname = "mixar.uv_rotate"
    bl_label = "Apply Rotate"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        # Get the transform values
        op_props = get_operator_properties(context, "transform.rotate")
        with context.temp_override(area=area, region=region, space_data=area.spaces.active):
            bpy.ops.transform.rotate(
                value=op_props.value,
                orient_type='GLOBAL',
                constraint_axis=(False, False, True)
            )

        # Reset the rotate value back to 0 after applying
        op_props.value = 0.0

        return {'FINISHED'}


class MIXAR_OT_uv_scale(Operator):
    """Apply scale transformation to selected UVs"""
    bl_idname = "mixar.uv_scale"
    bl_label = "Apply Scale"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        # Get the transform values
        op_props = get_operator_properties(context, "transform.resize")
        with context.temp_override(area=area, region=region, space_data=area.spaces.active):
            bpy.ops.transform.resize(
                value=(op_props.value[0], op_props.value[1], 1.0),
                orient_type='GLOBAL',
                constraint_axis=(False, False, False)
            )
        return {'FINISHED'}


classes = (
    MIXAR_OT_snap_selected,
    MIXAR_OT_snap_cursor,
    MIXAR_OT_mirror,
    MIXAR_OT_align,
    MIXAR_OT_align_rotation,
    MIXAR_OT_move_on_axis,
    MIXAR_OT_arrange_islands,
    MIXAR_OT_uv_translate,
    MIXAR_OT_uv_rotate,
    MIXAR_OT_uv_scale,
)
