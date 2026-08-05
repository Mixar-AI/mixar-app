# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sparse beat capture, review, removal, and video-generation handoff."""

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from ...core.capture import capture_beat, remove_beat
from ...core.handoff import prepare_video_generation
from ...core.shot_api import active_shot
from ...core.viewport import enter_camera_view


class MIXAR_OT_director_capture_beat(Operator):
    """Capture the current camera pose as the next sparse beat"""

    bl_idname = "mixar.director_capture_beat"
    bl_label = "Capture Camera Beat"
    bl_description = "Key the current camera and add a packed frame to Moodboard"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        shot = active_shot(context.scene) if state else None
        return bool(
            state and state.is_directing and shot and shot.state == 'DRAFT'
        )

    def execute(self, context):
        state = context.scene.mixar_director
        shot = active_shot(context.scene)
        try:
            beat = capture_beat(context, shot, state.beat_seconds)
        except Exception as exc:
            self.report({'ERROR'}, f"Could not capture camera beat: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Captured beat {len(shot.beats)} at frame {beat.frame}")
        return {'FINISHED'}


class MIXAR_OT_director_jump_beat(Operator):
    """Jump to a captured beat in camera view"""

    bl_idname = "mixar.director_jump_beat"
    bl_label = "View Beat"
    bl_options = {'REGISTER'}

    index: IntProperty(default=0, min=0)

    def execute(self, context):
        shot = active_shot(context.scene)
        if shot is None or self.index >= len(shot.beats):
            return {'CANCELLED'}
        shot.active_beat_index = self.index
        context.scene.frame_set(shot.beats[self.index].frame)
        try:
            enter_camera_view(context, shot.camera, remember=False)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_director_remove_beat(Operator):
    """Remove a beat, its camera keys, and its packed moodboard frame"""

    bl_idname = "mixar.director_remove_beat"
    bl_label = "Remove Beat"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=0, min=0)

    def execute(self, context):
        shot = active_shot(context.scene)
        if shot is None or not remove_beat(context.scene, shot, self.index):
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_director_preview(Operator):
    """Play the camera animation between the first and last sparse beats"""

    bl_idname = "mixar.director_preview"
    bl_label = "Preview Shot"
    bl_description = "Play this shot between its first and last camera beats"
    bl_options = {'REGISTER'}

    def execute(self, context):
        shot = active_shot(context.scene)
        if shot is None or not shot.beats:
            return {'CANCELLED'}
        scene = context.scene
        frames = sorted({beat.frame for beat in shot.beats})
        if len(frames) < 2:
            self.report({'INFO'}, "Capture at least two camera beats to preview")
            return {'CANCELLED'}
        scene.use_preview_range = True
        scene.frame_preview_start = frames[0]
        scene.frame_preview_end = frames[-1]
        if not context.screen.is_animation_playing:
            scene.frame_set(scene.frame_preview_start)
        try:
            enter_camera_view(context, shot.camera, remember=False)
            return bpy.ops.screen.animation_play()
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class MIXAR_OT_director_send_video(Operator):
    """Select camera beats and continue in catalog-driven Video Gen"""

    bl_idname = "mixar.director_send_video"
    bl_label = "Continue to Video Gen"
    bl_description = "Use these camera beats as ordered Video Gen references"
    bl_options = {'REGISTER'}

    def execute(self, context):
        shot = active_shot(context.scene)
        if shot is None:
            return {'CANCELLED'}
        try:
            count, focused = prepare_video_generation(context, shot)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if focused:
            self.report({'INFO'}, f"Selected {count} beats for Video Gen")
        else:
            self.report(
                {'INFO'},
                f"Selected {count} beats; open Moodboard > Video Gen",
            )
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_capture_beat,
    MIXAR_OT_director_jump_beat,
    MIXAR_OT_director_remove_beat,
    MIXAR_OT_director_preview,
    MIXAR_OT_director_send_video,
)
