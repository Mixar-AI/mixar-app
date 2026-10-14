# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reference-column actions for the generation panes."""

import bpy

from mixar.modules.agent_bubble.core.references import remove_reference


class MIXAR_OT_pane_remove_reference(bpy.types.Operator):
    bl_idname = 'mixar.pane_remove_reference'
    bl_label = 'Remove Reference'
    bl_description = 'Remove this reference from the generation input'
    bl_options = {'INTERNAL', 'UNDO'}

    attachment_path: bpy.props.StringProperty(options={'HIDDEN'})
    attachment_source: bpy.props.StringProperty(options={'HIDDEN'})

    def execute(self, context):
        if not remove_reference(context.scene, self.attachment_path, self.attachment_source):
            return {'CANCELLED'}
        context.window_manager.mixar_reference_scroll = 0
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
        return {'FINISHED'}


classes = (MIXAR_OT_pane_remove_reference,)
