# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Flow-inspired preset menus opened from the Director camera gate."""

from bpy.types import Panel

from ...constants import ASPECT_PRESETS, LENS_PRESET_ITEMS, LENS_TYPE_ITEMS
from ...core.camera_moves import CAMERA_MOVES
from ...core.shot_api import active_shot


def _active_camera(context):
    shot = active_shot(context.scene)
    camera = getattr(shot, "camera", None) if shot else None
    return shot, camera


def _aspect_is_active(render, width: int, height: int) -> bool:
    return render.resolution_x * height == render.resolution_y * width


class MIXAR_PT_director_lens_popover(Panel):
    """Lens projection types and focal-length presets in millimetres."""

    bl_idname = "MIXAR_PT_director_lens_popover"
    bl_label = "Lens"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        layout = self.layout
        shot, camera = _active_camera(context)
        if shot is None or camera is None or camera.type != 'CAMERA':
            layout.label(text="No active shot camera", icon='ERROR')
            return

        column = layout.column(align=False)
        column.enabled = shot.state == 'DRAFT'
        types = column.row(align=True)
        for key, label, _description, _index in LENS_TYPE_ITEMS:
            operator = types.operator(
                "mixar.director_set_lens_type",
                text=label,
                depress=camera.data.type == key,
            )
            operator.lens_type = key
        column.separator(factor=0.5)

        if camera.data.type == 'PERSP':
            presets = column.column(align=True)
            for lens_mm, label in LENS_PRESET_ITEMS:
                row = presets.row(align=True)
                operator = row.operator(
                    "mixar.director_set_lens",
                    text=label,
                    depress=abs(camera.data.lens - lens_mm) < 0.5,
                )
                operator.lens_mm = lens_mm
                row.label(text=f"{lens_mm}mm")
            column.separator(factor=0.35)
            column.prop(camera.data, "lens", text="Focal Length")
        elif camera.data.type == 'ORTHO':
            column.prop(camera.data, "ortho_scale", text="Scale")
        elif hasattr(camera.data, "panorama_type"):
            column.prop(camera.data, "panorama_type", text="Type")


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


class MIXAR_PT_director_moves_popover(Panel):
    """One-click cinematic camera moves captured as sparse keyframes."""

    bl_idname = "MIXAR_PT_director_moves_popover"
    bl_label = "Camera Moves"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        layout = self.layout
        state = context.scene.mixar_director
        shot, camera = _active_camera(context)
        if shot is None or camera is None or camera.type != 'CAMERA':
            layout.label(text="No active shot camera", icon='ERROR')
            return

        column = layout.column(align=False)
        column.enabled = shot.state == 'DRAFT'
        grid = column.grid_flow(
            row_major=True,
            columns=2,
            even_columns=True,
            even_rows=True,
            align=True,
        )
        for key, label, _tooltip in CAMERA_MOVES:
            grid.operator("mixar.director_camera_move", text=label).move = key
        column.separator(factor=0.4)
        column.prop(state, "beat_seconds", text="Keyframe Spacing")
        column.label(
            text="Each move captures keyframes from the current pose",
            icon='INFO',
        )


classes = (
    MIXAR_PT_director_lens_popover,
    MIXAR_PT_director_aspect_popover,
    MIXAR_PT_director_moves_popover,
)
