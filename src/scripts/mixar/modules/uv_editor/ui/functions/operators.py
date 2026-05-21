# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Functions Operators

Operators for UV functions (seam, pin, merge, split, hide, copy/paste) in the Mixar UV Editor.
"""

import bpy
from bpy.types import Operator

from mixar.modules.uv_editor.common.uv_utils import (
    poll_mixar_uv_edit_mode,
    with_uv_context,
    with_uv_context_and_region,
    get_operator_properties,
)


# =============================================================================
# UV Functions - Seam, Pin, Merge, Split, Hide
# =============================================================================

class MIXAR_OT_mark_seam(Operator):
    """Mark selected edges as seam"""
    bl_idname = "mixar.mark_seam"
    bl_label = "Mark Seam"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.mark_seam(clear=False)
        return {'FINISHED'}


class MIXAR_OT_clear_seam(Operator):
    """Clear seam from selected edges"""
    bl_idname = "mixar.clear_seam"
    bl_label = "Clear Seam"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.mark_seam(clear=True)
        return {'FINISHED'}


class MIXAR_OT_seams_from_islands(Operator):
    """Set seams based on UV islands"""
    bl_idname = "mixar.seams_from_islands"
    bl_label = "Seam from Islands"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.seams_from_islands()
        return {'FINISHED'}


class MIXAR_OT_stitch(Operator):
    """Stitch selected UV vertices by proximity (modal interactive)"""
    bl_idname = "mixar.stitch"
    bl_label = "Stitch"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        op_props = get_operator_properties(context, "uv.stitch")
        with context.temp_override(area=area, region=region):
            # Invoke with stored properties for modal interaction
            bpy.ops.uv.stitch(
                'INVOKE_DEFAULT',
                use_limit=op_props.use_limit,
                snap_islands=op_props.snap_islands,
                limit=op_props.limit,
                static_island=op_props.static_island,
                midpoint_snap=op_props.midpoint_snap,
                clear_seams=op_props.clear_seams,
                mode=op_props.mode,
            )
        return {'FINISHED'}


class MIXAR_OT_weld(Operator):
    """Weld selected UVs at center"""
    bl_idname = "mixar.weld"
    bl_label = "Merge at Center"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.weld()
        return {'FINISHED'}


class MIXAR_OT_merge_at_cursor(Operator):
    """Merge selected UVs at cursor"""
    bl_idname = "mixar.merge_at_cursor"
    bl_label = "Merge at Cursor"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.snap_selected(target='CURSOR')
        return {'FINISHED'}


class MIXAR_OT_remove_doubles(Operator):
    """Merge UVs by distance"""
    bl_idname = "mixar.remove_doubles"
    bl_label = "Merge by Distance"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        op_props = get_operator_properties(context, "uv.remove_doubles")
        with context.temp_override(area=area):
            bpy.ops.uv.remove_doubles(threshold=op_props.threshold)
        return {'FINISHED'}


class MIXAR_OT_select_split(Operator):
    """Split selected UVs"""
    bl_idname = "mixar.select_split"
    bl_label = "Split"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.select_split()
        return {'FINISHED'}


class MIXAR_OT_pin(Operator):
    """Pin selected UVs"""
    bl_idname = "mixar.pin"
    bl_label = "Pin"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.pin(clear=False)
        return {'FINISHED'}


class MIXAR_OT_unpin(Operator):
    """Unpin selected UVs"""
    bl_idname = "mixar.unpin"
    bl_label = "Unpin"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.pin(clear=True)
        return {'FINISHED'}


class MIXAR_OT_invert_pin(Operator):
    """Invert pin state of selected UVs"""
    bl_idname = "mixar.invert_pin"
    bl_label = "Invert Pin"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.pin(invert=True)
        return {'FINISHED'}


class MIXAR_OT_hide_selected(Operator):
    """Hide selected UV faces"""
    bl_idname = "mixar.hide_selected"
    bl_label = "Hide Selected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.hide(unselected=False)
        return {'FINISHED'}


class MIXAR_OT_reveal(Operator):
    """Reveal hidden UV faces"""
    bl_idname = "mixar.reveal"
    bl_label = "Reveal"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.reveal()
        return {'FINISHED'}


class MIXAR_OT_hide_unselected(Operator):
    """Hide unselected UV faces"""
    bl_idname = "mixar.hide_unselected"
    bl_label = "Hide Unselected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.hide(unselected=True)
        return {'FINISHED'}


class MIXAR_OT_copy_uvs(Operator):
    """Copy selected UVs"""
    bl_idname = "mixar.copy_uvs"
    bl_label = "Copy UVs"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.copy()
        return {'FINISHED'}


class MIXAR_OT_paste_uvs(Operator):
    """Paste UVs"""
    bl_idname = "mixar.paste_uvs"
    bl_label = "Paste UVs"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.paste()
        return {'FINISHED'}


classes = (
    MIXAR_OT_mark_seam,
    MIXAR_OT_clear_seam,
    MIXAR_OT_seams_from_islands,
    MIXAR_OT_stitch,
    MIXAR_OT_weld,
    MIXAR_OT_merge_at_cursor,
    MIXAR_OT_remove_doubles,
    MIXAR_OT_select_split,
    MIXAR_OT_pin,
    MIXAR_OT_unpin,
    MIXAR_OT_invert_pin,
    MIXAR_OT_hide_selected,
    MIXAR_OT_reveal,
    MIXAR_OT_hide_unselected,
    MIXAR_OT_copy_uvs,
    MIXAR_OT_paste_uvs,
)
