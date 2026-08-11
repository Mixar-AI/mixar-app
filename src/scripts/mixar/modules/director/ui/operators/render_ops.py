# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-shot motion-guide render operators for Director.

The Export to Moodboard popup itself is a native block
(``view3d_director_popup_render.cc``): its toggles and slider bind shot RNA
directly and its action rows invoke `mixar.director_send_keyframes` and the
operator below, so behavior keeps a single Python owner.
"""

from bpy.types import Operator

from ...core.render_outputs import render_job_active, start_shot_render
from ...core.shot_api import active_shot


class MIXAR_OT_director_render_videos(Operator):
    """Render selected shot passes and add the movies to Moodboard"""

    bl_idname = "mixar.director_render_videos"
    bl_label = "Render Videos to Moodboard"
    bl_description = "Render the shot beat span and add each video to Moodboard"
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
    MIXAR_OT_director_render_videos,
)
