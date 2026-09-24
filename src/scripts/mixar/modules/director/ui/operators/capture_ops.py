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
from ...core.playback import arm_single_play, disarm
from ...core.rotation_curves import repair_rotation_continuity
from ...core.shot_api import active_shot, release_preview_range
from ...core.viewport import enter_camera_view, find_view3d_context


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
        # While exploring, the shot camera is not being framed — a capture
        # would key its stale pose, so the F shortcut stays inert.
        return bool(
            state and state.is_directing and shot and shot.state == 'DRAFT'
            and state.navigation_mode != 'EXPLORE'
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


class MIXAR_OT_director_toggle_auto_key(Operator):
    """Toggle Blender's Auto Keying (the Timeline's record button): a
    keyframe after every camera move, and a recorded take while the timeline
    plays"""

    bl_idname = "mixar.director_toggle_auto_key"
    bl_label = "Auto Key"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing)

    def execute(self, context):
        state = context.scene.mixar_director
        state.auto_key = not state.auto_key
        self.report(
            {'INFO'},
            "Auto Key on: a keyframe after every camera move, and a "
            "recorded take while the timeline plays"
            if state.auto_key
            else "Auto Key off",
        )
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
    """Play the scene range to review or record a camera take"""

    bl_idname = "mixar.director_preview"
    bl_label = "Preview Shot"
    bl_description = "Play the scene range; Auto Key records live camera moves"
    bl_options = {'REGISTER', 'UNDO'}

    @staticmethod
    def _toggle_playback(context):
        """Start or stop the player ANCHORED ON THE VIEWPORT.

        Blender redraws the region playback was started from, plus whatever
        the Playback popover's `redraws_flag` adds — which is nothing by
        default. This button lives in the timeline dock, a region of its own,
        so starting the player from it ran the shot into a viewport that never
        redrew: the frames advanced and the picture did not move. Pressing
        Space works because the pointer is over the viewport, and that IS the
        region it starts from.

        Falling back to the bare call keeps a headless or viewport-less
        session working rather than refusing to play at all.
        """
        target = find_view3d_context(context)
        if target is None:
            return bpy.ops.screen.animation_play()
        window, area, region, space = target
        with context.temp_override(
            window=window, area=area, region=region, space_data=space
        ):
            return bpy.ops.screen.animation_play()

    def execute(self, context):
        scene = context.scene
        screen = getattr(context, "screen", None)
        if getattr(screen, "is_animation_playing", False):
            # Stopping stays available even before a recording has any beats.
            disarm()
            try:
                return self._toggle_playback(context)
            except Exception as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
        shot = active_shot(context.scene)
        if shot is None or shot.camera is None:
            return {'CANCELLED'}
        frames = sorted({beat.frame for beat in shot.beats})
        can_record = scene.mixar_director.auto_key and shot.state == 'DRAFT'
        if len(frames) < 2 and not can_record:
            self.report({'INFO'}, "Capture at least two keyframes to preview")
            return {'CANCELLED'}
        repair_rotation_continuity(shot.camera)
        # The SCENE's range, not the beats'. Preview used to clamp the
        # preview range to the first and last keyframe, so it looped between
        # two of them however long the scene was and the dock's own Start and
        # End fields did nothing. Those fields are what a director sets, so
        # they are what plays.
        release_preview_range(scene)
        start_frame = int(scene.frame_start)
        end_frame = int(scene.frame_end)
        scene.frame_set(start_frame)
        # A director reviewing a shot wants to SEE it, once — Blender's player
        # otherwise wraps at the end of the range and runs forever
        # (`core/playback.py` stops it on the end frame).
        arm_single_play(scene, start_frame, end_frame)
        try:
            enter_camera_view(context, shot.camera, remember=False)
            result = self._toggle_playback(context)
        except Exception as exc:
            disarm()
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if 'FINISHED' not in result:
            # A refusal used to be returned verbatim and read as success by
            # everything upstream, so a Preview that never started looked
            # exactly like one that did.
            disarm()
            self.report({'ERROR'}, "The animation player would not start")
            return {'CANCELLED'}
        return result


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
                f"Selected {count} keyframes; open Agent island > Video",
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


classes = (
    MIXAR_OT_director_capture_beat,
    MIXAR_OT_director_toggle_auto_key,
    MIXAR_OT_director_jump_beat,
    MIXAR_OT_director_remove_beat,
    MIXAR_OT_director_preview,
    MIXAR_OT_director_send_video,
    MIXAR_OT_director_send_keyframes,
)
