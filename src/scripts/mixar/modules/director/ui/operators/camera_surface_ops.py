# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Focused operators for the camera-gate controls in Director."""

import math

import bpy
from bpy.props import FloatProperty
from bpy.types import Operator

from ...core.shot_api import active_shot, refresh_manifest


def _editable_camera(context):
    state = getattr(context.scene, "mixar_director", None)
    shot = active_shot(context.scene) if state else None
    if (
        state is None
        or not state.is_directing
        or shot is None
        or shot.state != 'DRAFT'
        or shot.camera is None
        or shot.camera.type != 'CAMERA'
    ):
        return None, None
    return shot, shot.camera


class MIXAR_OT_director_show_fov_presets(Operator):
    """Open field-of-view presets beside the camera gate"""

    bl_idname = "mixar.director_show_fov_presets"
    bl_label = "Field of View"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        shot, camera = _editable_camera(context)
        return bool(shot and camera)

    def invoke(self, _context, _event):
        return bpy.ops.wm.call_panel(
            'INVOKE_DEFAULT',
            name="MIXAR_PT_director_fov_popover",
            keep_open=True,
        )


class MIXAR_OT_director_show_aspect_presets(Operator):
    """Open output-aspect presets beside the camera gate"""

    bl_idname = "mixar.director_show_aspect_presets"
    bl_label = "Aspect Ratio"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        shot, camera = _editable_camera(context)
        return bool(shot and camera)

    def invoke(self, _context, _event):
        return bpy.ops.wm.call_panel(
            'INVOKE_DEFAULT',
            name="MIXAR_PT_director_aspect_popover",
            keep_open=True,
        )


class MIXAR_OT_director_set_fov(Operator):
    """Apply a director-facing field-of-view preset"""

    bl_idname = "mixar.director_set_fov"
    bl_label = "Set Field of View"
    bl_options = {'REGISTER', 'UNDO'}

    angle_degrees: FloatProperty(
        name="Field of View",
        default=45.0,
        min=1.0,
        max=179.0,
    )

    def execute(self, context):
        shot, camera = _editable_camera(context)
        if shot is None or camera is None:
            return {'CANCELLED'}
        camera.data.type = 'PERSP'
        camera.data.angle = math.radians(self.angle_degrees)
        if shot.beats:
            refresh_manifest(context.scene, shot)
        if context.area is not None:
            context.area.tag_redraw()
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_show_fov_presets,
    MIXAR_OT_director_show_aspect_presets,
    MIXAR_OT_director_set_fov,
)
