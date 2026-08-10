# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Combined "Export to Moodboard" controls for one Director shot."""

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

# Short pill labels — the catalog labels ("Beauty Preview") are too long for a
# three-across toggle row and truncate.
_KIND_LABELS = {
    "BEAUTY": "Beauty",
    "CLAY": "Clay",
    "DEPTH": "Depth",
}


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
    """Export a Director shot to the Moodboard: keyframe stills and/or
    rendered motion-guide videos (Beauty / Clay / Depth)."""

    bl_idname = "MIXAR_PT_director_render_popover"
    bl_label = "Export to Moodboard"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 15

    def draw(self, context):
        scene = context.scene
        layout = self.layout
        shot = active_shot(scene)
        if shot is None:
            layout.label(text="No active Director shot", icon='ERROR')
            return

        head = layout.row(align=True)
        head.label(text=shot.name, icon='CAMERA_DATA')
        take = head.row()
        take.alignment = 'RIGHT'
        take.label(text=f"Take {shot.version}")

        beats = len(shot.beats)

        # Keyframe stills → Moodboard (the only path that boards captures).
        layout.separator(factor=0.5)
        layout.label(text="Keyframes")
        export = layout.row()
        export.scale_y = 1.3
        export.enabled = beats >= 1
        export.operator(
            "mixar.director_send_keyframes",
            text=f"Export {beats} Keyframe{'s' if beats != 1 else ''}",
            icon='EXPORT',
        )

        # Rendered motion-guide videos → Moodboard.
        layout.separator()
        layout.label(text="Render Guides")
        pills = layout.grid_flow(
            row_major=True, columns=3, even_columns=True, align=True
        )
        pills.enabled = not shot.render_is_running
        for kind, label, _description, _value in SHOT_RENDER_OUTPUT_ITEMS:
            pills.prop_enum(
                shot,
                "render_output_types",
                kind,
                text=_KIND_LABELS.get(kind, label),
                icon=_KIND_ICONS[kind],
            )
        resolution = layout.row(align=True)
        resolution.enabled = not shot.render_is_running
        resolution.prop(shot, "render_resolution_percentage", text="Resolution")

        if shot.render_is_running:
            layout.progress(factor=shot.render_progress, text=shot.render_status)
            layout.label(text="Press Esc in the render view to cancel", icon='INFO')
        else:
            if beats < 2:
                layout.label(text="Needs 2+ keyframes", icon='INFO')
            else:
                layout.label(text=_shot_summary(scene, shot), icon='TIME')
            kinds = ordered_render_kinds(shot.render_output_types)
            render = layout.row()
            render.scale_y = 1.3
            render.enabled = beats >= 2 and bool(kinds)
            count = len(kinds)
            render.operator(
                "mixar.director_render_videos",
                text=f"Render {count} Video{'s' if count != 1 else ''}",
                icon='RENDER_ANIMATION',
            )

        # Guide videos already exported for this shot.
        if shot.render_outputs:
            layout.separator()
            layout.label(text="On Moodboard", icon='FILE_MOVIE')
            recent = layout.column(align=True)
            for output in list(shot.render_outputs)[-3:][::-1]:
                image = output.image
                recent.label(
                    text=image.name if image is not None else "Missing video",
                    icon='FILE_MOVIE',
                )


classes = (MIXAR_PT_director_render_popover,)
