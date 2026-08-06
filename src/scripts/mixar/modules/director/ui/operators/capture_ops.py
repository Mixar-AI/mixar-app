# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sparse keyframe capture, review, removal, and video-generation handoff."""

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from ...core.board_export import send_keyframes_to_board
from ...core.capture import capture_beat, remove_beat
from ...core.handoff import prepare_video_generation
from ...core.shot_api import active_shot
from ...core.viewport import enter_camera_view


class MIXAR_OT_director_capture_beat(Operator):
    """Capture the current camera pose as the next sparse keyframe"""

    bl_idname = "mixar.director_capture_beat"
    bl_label = "Capture Keyframe"
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
            self.report({'ERROR'}, f"Could not capture keyframe: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Captured keyframe {len(shot.beats)} at frame {beat.frame}")
        return {'FINISHED'}


class MIXAR_OT_director_jump_beat(Operator):
    """Jump to a captured keyframe in camera view"""

    bl_idname = "mixar.director_jump_beat"
    bl_label = "View Keyframe"
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
    """Remove a keyframe, its camera keys, and its packed moodboard frame"""

    bl_idname = "mixar.director_remove_beat"
    bl_label = "Remove Keyframe"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=0, min=0)

    def execute(self, context):
        shot = active_shot(context.scene)
        if shot is None or not remove_beat(context.scene, shot, self.index):
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_director_preview(Operator):
    """Play the camera animation between the first and last sparse keyframes"""

    bl_idname = "mixar.director_preview"
    bl_label = "Preview Shot"
    bl_description = "Play this shot between its first and last keyframes"
    bl_options = {'REGISTER'}

    def execute(self, context):
        shot = active_shot(context.scene)
        if shot is None or not shot.beats:
            return {'CANCELLED'}
        scene = context.scene
        frames = sorted({beat.frame for beat in shot.beats})
        if len(frames) < 2:
            self.report({'INFO'}, "Capture at least two keyframes to preview")
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
    """Select keyframes and continue in catalog-driven Video Gen"""

    bl_idname = "mixar.director_send_video"
    bl_label = "Continue to Video Gen"
    bl_description = "Use these keyframes as ordered Video Gen references"
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
            self.report({'INFO'}, f"Selected {count} keyframes for Video Gen")
        else:
            self.report(
                {'INFO'},
                f"Selected {count} keyframes; open Moodboard > Video Gen",
            )
        return {'FINISHED'}


class MIXAR_OT_director_send_keyframes(Operator):
    """Send this shot's keyframes to the Moodboard as a shot-tagged group"""

    bl_idname = "mixar.director_send_keyframes"
    bl_label = "All Keyframes"
    bl_description = "Group every keyframe of this shot on the Moodboard"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        shot = active_shot(context.scene)
        if shot is None or not shot.beats:
            self.report({'WARNING'}, "No keyframes to send")
            return {'CANCELLED'}
        try:
            send_keyframes_to_board(context.scene, shot)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report(
            {'INFO'}, f"Sent {len(shot.beats)} keyframes to '{shot.name}'"
        )
        return {'FINISHED'}


class MIXAR_OT_director_send_moodboard(Operator):
    """Choose what to send to the Moodboard"""

    bl_idname = "mixar.director_send_moodboard"
    bl_label = "Send to Moodboard"
    bl_options = {'REGISTER'}

    def invoke(self, context, _event):
        def draw(menu, _context):
            layout = menu.layout
            layout.operator(
                "mixar.director_send_keyframes",
                text="All Keyframes",
                icon='IMAGE_DATA',
            )
            layout.operator(
                "mixar.director_show_render",
                text="Render Shot Videos...",
                icon='RENDER_ANIMATION',
            )
            layout.separator()
            layout.operator(
                "mixar.director_send_video",
                text="Continue to Video Gen",
                icon='FILE_MOVIE',
            )

        context.window_manager.popup_menu(
            draw, title="Send to Moodboard", icon='EXPORT'
        )
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_capture_beat,
    MIXAR_OT_director_jump_beat,
    MIXAR_OT_director_remove_beat,
    MIXAR_OT_director_preview,
    MIXAR_OT_director_send_video,
    MIXAR_OT_director_send_keyframes,
    MIXAR_OT_director_send_moodboard,
)
