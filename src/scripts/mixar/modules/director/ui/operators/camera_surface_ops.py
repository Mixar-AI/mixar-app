# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Focused operators for the camera-gate controls in Director."""

from bpy.props import EnumProperty
from bpy.types import Operator

from ...constants import LENS_TYPE_ITEMS
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


class MIXAR_OT_director_set_lens_type(Operator):
    """Switch the shot camera between lens projection types"""

    bl_idname = "mixar.director_set_lens_type"
    bl_label = "Set Lens Type"
    bl_options = {'REGISTER', 'UNDO'}

    lens_type: EnumProperty(
        name="Lens Type",
        items=LENS_TYPE_ITEMS,
        default="PERSP",
    )

    def execute(self, context):
        shot, camera = _editable_camera(context)
        if shot is None or camera is None:
            return {'CANCELLED'}
        camera.data.type = self.lens_type
        if shot.beats:
            refresh_manifest(context.scene, shot)
        if context.area is not None:
            context.area.tag_redraw()
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_set_lens_type,
)
