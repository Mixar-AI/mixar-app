# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Simple directing controls over native Blender camera/output properties."""

from bpy.props import EnumProperty, IntProperty
from bpy.types import Operator

from ...constants import ASPECT_PRESETS
from ...core.shot_api import active_shot, refresh_manifest
from ...core.viewport import enter_precise_mode, invoke_walk


def _editable_shot(context):
    shot = active_shot(context.scene)
    if shot is None or shot.state != 'DRAFT' or shot.camera is None:
        return None
    return shot


class MIXAR_OT_director_navigate(Operator):
    """Rough-in the camera with Blender's native WASD walk navigation"""

    bl_idname = "mixar.director_navigate"
    bl_label = "Navigate"
    bl_description = "Move the camera with WASD and mouse; click to confirm"

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing and _editable_shot(context))

    def invoke(self, context, _event):
        shot = _editable_shot(context)
        context.scene.mixar_director.navigation_mode = 'NAVIGATE'
        try:
            return invoke_walk(context, shot.camera)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class MIXAR_OT_director_precise(Operator):
    """Select the shot camera for native gizmo-based adjustment"""

    bl_idname = "mixar.director_precise"
    bl_label = "Precise"
    bl_description = "Adjust the camera with Blender's transform gizmos"

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing and _editable_shot(context))

    def execute(self, context):
        shot = _editable_shot(context)
        context.scene.mixar_director.navigation_mode = 'PRECISE'
        try:
            enter_precise_mode(context, shot.camera)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_director_set_lens(Operator):
    """Apply a familiar focal-length preset to the active shot camera"""

    bl_idname = "mixar.director_set_lens"
    bl_label = "Set Lens"
    bl_options = {'REGISTER', 'UNDO'}

    lens_mm: IntProperty(name="Lens", default=35, min=1, max=500)

    def execute(self, context):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        shot.camera.data.lens = self.lens_mm
        if shot.beats:
            refresh_manifest(context.scene, shot)
        return {'FINISHED'}


class MIXAR_OT_director_set_aspect(Operator):
    """Apply a director-facing aspect preset to native render settings"""

    bl_idname = "mixar.director_set_aspect"
    bl_label = "Set Aspect"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(
        name="Aspect",
        items=tuple(
            (key, values[0], f"Set {values[0]} output", index)
            for index, (key, values) in enumerate(ASPECT_PRESETS.items())
        ),
        default="WIDE",
    )

    def execute(self, context):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        _label, width, height = ASPECT_PRESETS[self.preset]
        render = context.scene.render
        render.resolution_x = width
        render.resolution_y = height
        render.pixel_aspect_x = 1.0
        render.pixel_aspect_y = 1.0
        if shot.beats:
            refresh_manifest(context.scene, shot)
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_navigate,
    MIXAR_OT_director_precise,
    MIXAR_OT_director_set_lens,
    MIXAR_OT_director_set_aspect,
)

