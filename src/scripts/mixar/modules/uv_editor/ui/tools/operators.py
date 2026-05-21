# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Tools Operators

Operators for UV sculpt tools in the Mixar UV Editor.
"""

import bpy
from bpy.types import Operator

from mixar.modules.uv_editor.common.uv_utils import (
    get_mixar_uv_image_editor,
    get_window_region,
    poll_mixar_uv_mode,
    with_uv_context,
    with_uv_context_and_region,
)


class MIXAR_OT_activate_uv_sculpt_grab(Operator):
    """Activate UV Sculpt Grab tool"""
    bl_idname = "mixar.activate_uv_sculpt_grab"
    bl_label = "Activate Grab Tool"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        with context.temp_override(area=area, region=region, space_data=area.spaces.active):
            bpy.ops.wm.tool_set_by_id(name='sculpt.uv_sculpt_grab')
        return {'FINISHED'}


class MIXAR_OT_activate_uv_sculpt_relax(Operator):
    """Activate UV Sculpt Relax tool"""
    bl_idname = "mixar.activate_uv_sculpt_relax"
    bl_label = "Activate Relax Tool"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        with context.temp_override(area=area, region=region, space_data=area.spaces.active):
            bpy.ops.wm.tool_set_by_id(name='sculpt.uv_sculpt_relax')
        return {'FINISHED'}


class MIXAR_OT_activate_uv_sculpt_pinch(Operator):
    """Activate UV Sculpt Pinch tool"""
    bl_idname = "mixar.activate_uv_sculpt_pinch"
    bl_label = "Activate Pinch Tool"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        with context.temp_override(area=area, region=region, space_data=area.spaces.active):
            bpy.ops.wm.tool_set_by_id(name='sculpt.uv_sculpt_pinch')
        return {'FINISHED'}


class MIXAR_OT_activate_rip_region(Operator):
    """Activate Rip Region tool"""
    bl_idname = "mixar.activate_rip_region"
    bl_label = "Activate Rip Region Tool"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        with context.temp_override(area=area, region=region, space_data=area.spaces.active):
            bpy.ops.wm.tool_set_by_id(name='builtin.rip_region')
        return {'FINISHED'}


class MIXAR_OT_view_selected(Operator):
    """Frame selected UVs in view"""
    bl_idname = "mixar.view_selected"
    bl_label = "Frame Selected"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        with context.temp_override(area=area, region=region, space_data=area.spaces.active):
            bpy.ops.image.view_selected()
        return {'FINISHED'}


class MIXAR_OT_view_all(Operator):
    """Frame all UVs in view"""
    bl_idname = "mixar.view_all"
    bl_label = "Frame All"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        with context.temp_override(area=area, region=region, space_data=area.spaces.active):
            bpy.ops.image.view_all()
        return {'FINISHED'}


class MIXAR_OT_view_center_cursor(Operator):
    """Center view to cursor"""
    bl_idname = "mixar.view_center_cursor"
    bl_label = "Center View to Cursor"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        with context.temp_override(area=area, region=region, space_data=area.spaces.active):
            bpy.ops.image.view_center_cursor()
        return {'FINISHED'}


classes = (
    MIXAR_OT_activate_uv_sculpt_grab,
    MIXAR_OT_activate_uv_sculpt_relax,
    MIXAR_OT_activate_uv_sculpt_pinch,
    MIXAR_OT_activate_rip_region,
    MIXAR_OT_view_selected,
    MIXAR_OT_view_all,
    MIXAR_OT_view_center_cursor,
)
