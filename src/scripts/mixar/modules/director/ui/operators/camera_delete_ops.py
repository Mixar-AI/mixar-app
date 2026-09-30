# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Delete a camera from the "My Cameras" card."""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from mixar.modules.common.i18n import rpt_
from ...core.camera_delete import delete_camera


class MIXAR_OT_director_delete_camera(Operator):
    """Delete this camera and every shot that directs it"""

    bl_idname = "mixar.director_delete_camera"
    bl_label = "Delete Camera"
    bl_description = (
        "Remove this camera from the scene, along with the shots and camera "
        "motion that belong to it"
    )
    bl_options = {'REGISTER', 'UNDO'}

    camera_name: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return getattr(context, "scene", None) is not None

    def invoke(self, context, event):
        # Destructive and unprompted from a small chip: confirm first. The
        # camera's takes and its keyed motion go with it.
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        camera = bpy.data.objects.get(self.camera_name)
        if camera is None or camera.type != 'CAMERA':
            # The row's name is read at draw time; by the time the click
            # lands the camera may already be gone (outliner, a script).
            self.report({'WARNING'}, "That camera is no longer in the file")
            return {'CANCELLED'}
        name = camera.name
        try:
            removed = delete_camera(context.scene, camera)
        except Exception as exc:
            self.report({'ERROR'}, rpt_("Could not delete {name}: {error}").format(name=name, error=exc))
            return {'CANCELLED'}
        if removed:
            self.report({'INFO'}, rpt_("Deleted {name} and {count} shot(s)").format(name=name, count=removed))
        else:
            self.report({'INFO'}, rpt_("Deleted {name}").format(name=name))
        return {'FINISHED'}


classes = (MIXAR_OT_director_delete_camera,)
