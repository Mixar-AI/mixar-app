# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keep long notification content reachable without zooming the viewport."""

import bpy

from ...toast_renderer import scroll_toast


class NOTIFICATION_OT_toast_scroll(bpy.types.Operator):
    bl_idname = 'notification.toast_scroll'
    bl_label = 'Scroll Notification'
    bl_options = {'INTERNAL'}

    mouse_x: bpy.props.IntProperty()
    mouse_y: bpy.props.IntProperty()
    delta: bpy.props.FloatProperty()

    def execute(self, context):
        region = context.region
        if region and scroll_toast(region.as_pointer(), self.mouse_x, self.mouse_y, self.delta):
            region.tag_redraw()
            return {'FINISHED'}
        return {'CANCELLED'}


classes = (NOTIFICATION_OT_toast_scroll,)
