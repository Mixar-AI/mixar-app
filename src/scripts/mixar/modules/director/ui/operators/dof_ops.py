# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Depth-of-field controls for the shot camera.

The popup binds ``camera.data.dof``'s own properties for everything Blender
already expresses as a value (the switch, the f-stop, the distance). These
two operators cover what it does not: focusing on the subject the camera is
already tracking, and the whole-stop presets a director asks for by name.
"""

from bpy.props import EnumProperty, FloatProperty
from bpy.types import Operator

from ...core.dof import camera_dof, clear_focus_object, set_focus_object
from ...core.shot_api import active_shot

FOCUS_MODE_ITEMS = (
    ('SUBJECT', "Focus on Subject", "Focus on the object this camera tracks"),
    ('CLEAR', "Clear Focus", "Release the focus object and hold its distance"),
)


def _editable_shot(context):
    shot = active_shot(context.scene)
    if shot is None or shot.state != 'DRAFT' or shot.camera is None:
        return None
    return shot


class MIXAR_OT_director_set_focus(Operator):
    """Focus the shot camera on its tracked subject, or release it"""

    bl_idname = "mixar.director_set_focus"
    bl_label = "Focus"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=FOCUS_MODE_ITEMS,
        default='SUBJECT',
    )

    @classmethod
    def poll(cls, context):
        return _editable_shot(context) is not None

    def execute(self, context):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        if self.mode == 'CLEAR':
            if not clear_focus_object(shot.camera):
                self.report({'INFO'}, "Nothing was in focus")
                return {'CANCELLED'}
            self.report({'INFO'}, "Focus released at its last distance")
            return {'FINISHED'}
        target = getattr(shot, "track_target", None)
        if target is None:
            # The one thing this mode needs, and the eyedropper beside it is
            # how to get it — say so instead of failing silently.
            self.report({'ERROR'}, "Pick a subject with the eyedropper first")
            return {'CANCELLED'}
        if not set_focus_object(shot.camera, target):
            self.report({'ERROR'}, "This camera cannot hold a focus object")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Focused on {target.name}")
        return {'FINISHED'}


class MIXAR_OT_director_set_fstop(Operator):
    """Set the aperture to a whole stop"""

    bl_idname = "mixar.director_set_fstop"
    bl_label = "Aperture"
    bl_options = {'REGISTER', 'UNDO'}

    fstop: FloatProperty(
        name="f-stop",
        description="Aperture to apply, as an f-number",
        default=2.8,
        min=0.01,
        soft_min=0.95,
        soft_max=22.0,
    )

    @classmethod
    def poll(cls, context):
        return _editable_shot(context) is not None

    def execute(self, context):
        shot = _editable_shot(context)
        dof = camera_dof(shot.camera) if shot is not None else None
        if dof is None:
            return {'CANCELLED'}
        dof.aperture_fstop = float(self.fstop)
        # Choosing an aperture IS asking for depth of field; leaving the
        # switch off would make the preset do nothing visible.
        dof.use_dof = True
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_set_focus,
    MIXAR_OT_director_set_fstop,
)
