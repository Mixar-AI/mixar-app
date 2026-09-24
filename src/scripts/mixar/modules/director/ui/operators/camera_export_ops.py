# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render a natively animated camera to the Moodboard.

Distinct from `mixar.director_render_videos`, which renders a Director SHOT
(its camera, its beats, its progress). This one serves a camera keyframed
through Blender's own timeline and is reachable with no Director session at
all — see `ui/menus/camera_export_menu.py`.

`poll` guards only what is genuinely un-invokable (a render already running).
Every other blocker is reported by `execute` with the reason the popup
already shows, so a press can never fail silently.
"""

from bpy.types import Operator

from ...core.camera_export import current_plan, export_settings, render_busy
from ...core.render_outputs import start_camera_render


class MIXAR_OT_render_camera_to_moodboard(Operator):
    """Render this camera's animation and add the videos to Moodboard"""

    bl_idname = "mixar.render_camera_to_moodboard"
    bl_label = "Render to Moodboard"
    bl_description = (
        "Render the camera's keyframed motion as Beauty, Clay and/or Depth "
        "videos and add them to the Moodboard"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and not render_busy()

    def execute(self, context):
        scene = context.scene
        settings = export_settings(scene)
        if settings is None:
            self.report({'ERROR'}, "Camera export is unavailable")
            return {'CANCELLED'}
        camera, plan = current_plan(context, settings=settings)
        if plan is None or not plan.ok:
            self.report({'ERROR'}, plan.reason if plan else "Nothing to render")
            return {'CANCELLED'}
        try:
            count = start_camera_render(context, scene, settings, camera, plan)
        except Exception as exc:
            self.report({'ERROR'}, f"Could not render camera videos: {exc}")
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Rendering {count} video{'s' if count != 1 else ''} to Moodboard",
        )
        return {'FINISHED'}


classes = (
    MIXAR_OT_render_camera_to_moodboard,
)
