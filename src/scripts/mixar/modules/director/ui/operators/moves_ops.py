# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One-click camera move and character animation preset operators."""

from bpy.props import EnumProperty
from bpy.types import Operator

from ...core.animation_presets import ANIMATION_PRESETS, apply_animation_preset
from ...core.camera_moves import CAMERA_MOVES, apply_camera_move
from ...core.shot_api import active_shot


def _editable_shot(context):
    shot = active_shot(context.scene)
    if shot is None or shot.state != 'DRAFT' or shot.camera is None:
        return None
    return shot


class MIXAR_OT_director_camera_move(Operator):
    """Capture a preset camera move as sparse shot keyframes"""

    bl_idname = "mixar.director_camera_move"
    bl_label = "Camera Move"
    bl_options = {'REGISTER', 'UNDO'}

    move: EnumProperty(
        name="Move",
        items=tuple(
            (key, label, tooltip, index)
            for index, (key, label, tooltip) in enumerate(CAMERA_MOVES)
        ),
        default="ORBIT_LEFT",
    )

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing and _editable_shot(context))

    def execute(self, context):
        state = context.scene.mixar_director
        shot = _editable_shot(context)
        try:
            frames = apply_camera_move(context, shot, state, self.move)
        except Exception as exc:
            self.report({'ERROR'}, f"Could not apply the move: {exc}")
            return {'CANCELLED'}
        if not frames:
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Added {len(frames)} keyframes through frame {frames[-1]}",
        )
        return {'FINISHED'}


class MIXAR_OT_director_apply_animation(Operator):
    """Key a blocking-level motion preset on the selected character"""

    bl_idname = "mixar.director_apply_animation"
    bl_label = "Animate Character"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(
        name="Preset",
        items=tuple(
            (key, label, tooltip, index)
            for index, (key, label, tooltip) in enumerate(ANIMATION_PRESETS)
        ),
        default="WALK",
    )

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        obj = context.active_object
        return bool(
            state
            and state.is_directing
            and obj is not None
            and obj.type != 'CAMERA'
        )

    def execute(self, context):
        state = context.scene.mixar_director
        obj = context.active_object
        try:
            end = apply_animation_preset(
                context.scene, obj, self.preset, state.animation_seconds
            )
        except Exception as exc:
            self.report({'ERROR'}, f"Could not animate {obj.name}: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Keyed {obj.name} through frame {end}")
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_camera_move,
    MIXAR_OT_director_apply_animation,
)
