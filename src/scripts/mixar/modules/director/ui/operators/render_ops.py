# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export to Moodboard: the shot's keyframe images and videos.

The popup itself is a native block (``view3d_director_popup_render.cc``):
its toggles and size presets bind shot RNA directly and its one action runs
`mixar.director_export_to_moodboard` below, so behavior keeps a single
Python owner. `mixar.director_render_videos` stays as the videos-only entry
point scripts and the agent already call.
"""

from bpy.types import Operator

from ...core.board_export import export_plan, send_keyframes_to_board
from ...core.render_outputs import render_job_active, start_shot_render
from ...core.shot_api import active_shot


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'s' if count != 1 else ''}"


class MIXAR_OT_director_export_to_moodboard(Operator):
    """Send the chosen keyframe images and videos to the Moodboard"""

    bl_idname = "mixar.director_export_to_moodboard"
    bl_label = "Send to Moodboard"
    bl_description = (
        "Add the chosen keyframe images to the Moodboard, and render the "
        "chosen videos into it in the background"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        shot = active_shot(context.scene) if state else None
        if not (state and state.is_directing and shot and shot.camera):
            return False
        rendering = bool(shot.render_is_running or render_job_active())
        return export_plan(shot, rendering=rendering).anything

    def execute(self, context):
        shot = active_shot(context.scene)
        if shot is None:
            return {'CANCELLED'}
        rendering = bool(shot.render_is_running or render_job_active())
        plan = export_plan(shot, rendering=rendering)
        if not plan.anything:
            self.report({'WARNING'}, plan.video_blocker or "Choose what to send")
            return {'CANCELLED'}
        sent = []
        if plan.images:
            try:
                added = send_keyframes_to_board(context.scene, shot)
            except Exception as exc:
                self.report({'ERROR'}, f"Could not send keyframe images: {exc}")
                return {'CANCELLED'}
            sent.append(
                f"{_plural(added, 'image')} added"
                if added
                else "images already on the Moodboard"
            )
        if plan.videos:
            try:
                count = start_shot_render(context, shot)
            except Exception as exc:
                # The images already went; say what did not.
                self.report({'ERROR'}, f"Could not render the videos: {exc}")
                return {'FINISHED'} if plan.images else {'CANCELLED'}
            sent.append(f"rendering {_plural(count, 'video')}")
        elif plan.video_blocker:
            # Chosen but not possible now: say so rather than drop them quietly.
            sent.append(plan.video_blocker.lower())
        self.report({'INFO'}, "Moodboard: " + ", ".join(sent))
        return {'FINISHED'}


class MIXAR_OT_director_render_videos(Operator):
    """Render selected shot passes and add the movies to Moodboard"""

    bl_idname = "mixar.director_render_videos"
    bl_label = "Render Videos to Moodboard"
    bl_description = "Render this shot's chosen videos into the Moodboard"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        shot = active_shot(context.scene) if state else None
        return bool(
            state
            and state.is_directing
            and shot
            and shot.camera
            and len(shot.beats) >= 2
            and shot.render_output_types
            and not shot.render_is_running
            and not render_job_active()
        )

    def execute(self, context):
        shot = active_shot(context.scene)
        if shot is None:
            return {'CANCELLED'}
        try:
            count = start_shot_render(context, shot)
        except Exception as exc:
            self.report({'ERROR'}, f"Could not render shot videos: {exc}")
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Rendering {count} shot video{'s' if count != 1 else ''} to Moodboard",
        )
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_export_to_moodboard,
    MIXAR_OT_director_render_videos,
)
