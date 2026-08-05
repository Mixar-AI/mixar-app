# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Flow-inspired preset menus opened from the Director camera gate."""

import math

from bpy.types import Panel

from ...constants import ASPECT_PRESETS, FOV_PRESETS_DEGREES
from ...core.shot_api import active_shot


def _active_camera(context):
    shot = active_shot(context.scene)
    camera = getattr(shot, "camera", None) if shot else None
    return shot, camera


def _aspect_is_active(render, width: int, height: int) -> bool:
    return render.resolution_x * height == render.resolution_y * width


class MIXAR_PT_director_fov_popover(Panel):
    """Named field-of-view presets for the active Director camera."""

    bl_idname = "MIXAR_PT_director_fov_popover"
    bl_label = "Field of View"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        layout = self.layout
        shot, camera = _active_camera(context)
        if shot is None or camera is None or camera.type != 'CAMERA':
            layout.label(text="No active shot camera", icon='ERROR')
            return

        current_degrees = math.degrees(camera.data.angle)
        column = layout.column(align=True)
        column.enabled = shot.state == 'DRAFT'
        for _key, label, degrees in FOV_PRESETS_DEGREES:
            row = column.row(align=True)
            operator = row.operator(
                "mixar.director_set_fov",
                text=label,
                depress=abs(current_degrees - degrees) < 0.5,
            )
            operator.angle_degrees = degrees
            row.label(text=f"{degrees:g}°")


class MIXAR_PT_director_aspect_popover(Panel):
    """Named output-aspect presets for the active Director shot."""

    bl_idname = "MIXAR_PT_director_aspect_popover"
    bl_label = "Aspect Ratio"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        layout = self.layout
        shot, camera = _active_camera(context)
        if shot is None or camera is None or camera.type != 'CAMERA':
            layout.label(text="No active shot camera", icon='ERROR')
            return

        column = layout.column(align=True)
        column.enabled = shot.state == 'DRAFT'
        render = context.scene.render
        for preset, (display, width, height) in ASPECT_PRESETS.items():
            title, ratio = display.rsplit(" · ", 1)
            row = column.row(align=True)
            selected = _aspect_is_active(render, width, height)
            operator = row.operator(
                "mixar.director_set_aspect",
                text=title,
                depress=selected,
            )
            operator.preset = preset
            ratio_operator = row.operator(
                "mixar.director_set_aspect",
                text=ratio,
                depress=selected,
            )
            ratio_operator.preset = preset


classes = (
    MIXAR_PT_director_fov_popover,
    MIXAR_PT_director_aspect_popover,
)
