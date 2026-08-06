# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Focused per-shot video-render controls for the Director surface."""

from bpy.types import Panel

from ...constants import SHOT_RENDER_OUTPUT_ITEMS
from ...core.render_spec import (
    ordered_render_kinds,
    render_duration_seconds,
    render_frame_bounds,
)
from ...core.shot_api import active_shot


_KIND_ICONS = {
    "BEAUTY": 'SHADING_RENDERED',
    "CLAY": 'MESH_UVSPHERE',
    "DEPTH": 'IMAGE_ZDEPTH',
}


def _section(layout, title, icon='NONE'):
    box = layout.mixar_section() if hasattr(layout, "mixar_section") else layout.box()
    column = box.column(align=False)
    column.label(text=title, icon=icon)
    column.separator(factor=0.35)
    return column


def _shot_summary(scene, shot) -> str:
    frame_start, frame_end = render_frame_bounds(beat.frame for beat in shot.beats)
    duration = render_duration_seconds(
        frame_start,
        frame_end,
        scene.render.fps,
        scene.render.fps_base,
    )
    scale = shot.render_resolution_percentage / 100.0
    width = max(1, round(scene.render.resolution_x * scale))
    height = max(1, round(scene.render.resolution_y * scale))
    return f"{duration:.1f}s · {width} × {height} · {scene.render.fps:g} fps"


class MIXAR_PT_director_render_popover(Panel):
    """Select and render motion-guide videos for one Director shot."""

    bl_idname = "MIXAR_PT_director_render_popover"
    bl_label = "Shot Renders"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        layout = self.layout
        shot = active_shot(context.scene)
        if shot is None:
            layout.label(text="No active Director shot", icon='ERROR')
            return

        header = layout.row(align=True)
        header.label(text=shot.name, icon='CAMERA_DATA')
        header.label(text=f"T{shot.version}")

        renders = _section(layout, "Render Videos", icon='RENDER_ANIMATION')
        choices = renders.grid_flow(
            row_major=True,
            columns=3,
            even_columns=True,
            even_rows=True,
            align=True,
        )
        choices.enabled = not shot.render_is_running
        for kind, label, _description, _value in SHOT_RENDER_OUTPUT_ITEMS:
            choices.prop_enum(
                shot,
                "render_output_types",
                kind,
                text=label,
                icon=_KIND_ICONS[kind],
            )
        resolution = renders.row(align=True)
        resolution.enabled = not shot.render_is_running
        resolution.prop(shot, "render_resolution_percentage", text="Resolution")

        if len(shot.beats) < 2:
            renders.label(text="Capture at least two camera beats", icon='INFO')
        else:
            renders.label(text=_shot_summary(context.scene, shot), icon='TIME')

        if shot.render_is_running:
            progress = layout.row()
            progress.progress(factor=shot.render_progress, text=shot.render_status)
            layout.label(text="Press Esc in the render view to cancel", icon='INFO')
        else:
            kinds = ordered_render_kinds(shot.render_output_types)
            action = layout.row()
            action.scale_y = 1.35
            action.enabled = len(shot.beats) >= 2 and bool(kinds)
            count = len(kinds)
            label = f"Render {count} Video{'s' if count != 1 else ''} to Moodboard"
            action.operator(
                "mixar.director_render_videos",
                text=label,
                icon='RENDER_ANIMATION',
            )

        if shot.render_outputs:
            recent = _section(layout, "On Moodboard", icon='FILE_MOVIE')
            for output in list(shot.render_outputs)[-3:][::-1]:
                image = output.image
                name = image.name if image is not None else "Missing video"
                recent.label(text=name, icon='FILE_MOVIE')


classes = (MIXAR_PT_director_render_popover,)
