# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Hide/show the floating object controls with a real tooltip.

The bar's × and the scene toolbar's **Object Controls** button used the stock
``wm.context_toggle``, whose tooltip is the generic "Context Toggle / Toggle a
context value". Writing the same RNA property keeps the native
hidden-by-user flag, so the next selection still restores the bar.
"""
import bpy
from bpy.props import BoolProperty


class MIXAR_OT_zen_object_controls_show(bpy.types.Operator):
    bl_idname = "mixar.zen_object_controls_show"
    bl_label = "Object Controls"
    bl_description = "Show or hide the floating controls for the selected object"
    bl_options = {'INTERNAL'}

    show: BoolProperty(options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        if properties.show:
            return "Show the floating controls for the selected object"
        return "Hide these controls until the selection changes"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.type == 'VIEW_3D'

    def execute(self, context):
        context.space_data.show_region_tool_header = self.show
        return {'FINISHED'}


classes = (MIXAR_OT_zen_object_controls_show,)
