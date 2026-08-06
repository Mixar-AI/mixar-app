# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Focused popovers opened by the native Director viewport shell."""

from bpy.types import Panel

from mixar.modules.common.utils.ui_utils import draw_multiline_text_input

from ...constants import ASPECT_PRESETS, LENS_PRESETS_MM
from ...core.shot_api import active_shot


def _section(layout, title, icon='NONE'):
    box = layout.mixar_section() if hasattr(layout, "mixar_section") else layout.box()
    column = box.column(align=False)
    column.label(text=title, icon=icon)
    column.separator(factor=0.35)
    return column


def _draw_empty(layout, scene):
    box = _section(layout, "Direct a Camera", icon='CAMERA_DATA')
    box.label(text="Move through the scene and capture")
    box.label(text="only the frames that define the shot.")
    box.separator(factor=0.7)
    button = box.row()
    button.scale_y = 1.45
    label = "Direct Scene Camera" if scene.camera else "Create Camera & Direct"
    button.operator("mixar.director_start", text=label, icon='VIEW_CAMERA')
    if scene.camera:
        box.operator(
            "mixar.director_new_shot",
            text="Create a New Shot Camera",
            icon='ADD',
        )


def _draw_shot_picker(layout, state):
    row = layout.row(align=True)
    icon = 'DOWNARROW_HLT' if state.show_shots else 'RIGHTARROW'
    row.prop(
        state,
        "show_shots",
        text=f"Shots ({len(state.shots)})",
        icon=icon,
        emboss=False,
    )
    row.operator("mixar.director_new_shot", text="", icon='ADD')
    remove = row.row(align=True)
    remove.enabled = bool(state.shots) and not state.is_directing
    remove.operator("mixar.director_remove_shot", text="", icon='REMOVE')
    if state.show_shots:
        listing = layout.row()
        listing.enabled = not state.is_directing
        listing.template_list(
            "MIXAR_UL_director_shots",
            "",
            state,
            "shots",
            state,
            "active_shot_index",
            rows=min(4, max(2, len(state.shots))),
        )


def _draw_shot_header(layout, state, shot):
    row = layout.row(align=True)
    name = row.row(align=True)
    name.enabled = shot.state == 'DRAFT'
    name.prop(shot, "name", text="", icon='CAMERA_DATA')
    status_icon = 'LOCKED' if shot.state == 'LOCKED' else 'UNLOCKED'
    row.label(text=f"T{shot.version}", icon=status_icon)

    camera_row = layout.row(align=True)
    camera_row.enabled = not state.is_directing and shot.state == 'DRAFT'
    camera_row.prop(shot, "camera", text="Camera")


def _draw_session(layout, state, shot):
    if shot.state == 'LOCKED':
        box = _section(layout, "Locked Take", icon='LOCKED')
        box.label(text=f"{len(shot.beats)} keyframes are frozen.")
        if shot.manifest_text_name:
            box.label(text=shot.manifest_text_name, icon='TEXT')
        button = box.row()
        button.scale_y = 1.25
        button.operator("mixar.director_new_take", icon='DUPLICATE')
        return

    box = _section(layout, "Camera Control", icon='ORIENTATION_VIEW')
    if state.is_directing:
        modes = box.row(align=True)
        modes.operator(
            "mixar.director_navigate",
            text="Navigate",
            icon='VIEW_PAN',
            depress=state.navigation_mode == 'NAVIGATE',
        )
        modes.operator(
            "mixar.director_precise",
            text="Precise",
            icon='ORIENTATION_GIMBAL',
            depress=state.navigation_mode == 'PRECISE',
        )
        box.label(text="Navigate: WASD + mouse · click to confirm", icon='INFO')
        toggles = box.row(align=True)
        toggles.prop(state, "level_horizon", text="Fix Z", toggle=True)
        toggles.prop(state, "auto_key", text="Auto Key", toggle=True)
        if state.navigation_mode == 'PRECISE' and shot.camera is not None:
            precise = box.box().column(align=True)
            precise.label(text="Fine Tune", icon='ORIENTATION_GIMBAL')
            precise.prop(shot.camera, "location", text="Position")
            rotation_prop = (
                "rotation_quaternion"
                if shot.camera.rotation_mode == 'QUATERNION'
                else "rotation_axis_angle"
                if shot.camera.rotation_mode == 'AXIS_ANGLE'
                else "rotation_euler"
            )
            precise.prop(shot.camera, rotation_prop, text="Rotation")
        box.row().operator("mixar.director_finish", icon='CHECKMARK')
    else:
        start = box.row()
        start.scale_y = 1.25
        start.operator("mixar.director_start", text="Resume Directing", icon='VIEW_CAMERA')


def _aspect_is_active(render, preset) -> bool:
    _label, width, height = ASPECT_PRESETS[preset]
    return render.resolution_x * height == render.resolution_y * width


def _draw_camera_settings(layout, scene, state, shot):
    camera = shot.camera
    if camera is None or camera.type != 'CAMERA':
        layout.label(text="Choose a camera to continue", icon='ERROR')
        return
    editable = shot.state == 'DRAFT'
    box = _section(layout, "Framing", icon='CAMERA_DATA')
    content = box.column(align=False)
    content.enabled = editable

    content.prop(camera.data, "type", text="Projection")
    lens_row = content.row(align=True)
    lens_row.enabled = camera.data.type == 'PERSP'
    for lens in LENS_PRESETS_MM:
        operator = lens_row.operator(
            "mixar.director_set_lens",
            text=f"{lens}",
            depress=abs(camera.data.lens - lens) < 0.1,
        )
        operator.lens_mm = lens
    if camera.data.type == 'PERSP':
        content.prop(camera.data, "lens", text="Lens")
    elif camera.data.type == 'ORTHO':
        content.prop(camera.data, "ortho_scale", text="Scale")

    content.separator(factor=0.45)
    aspect_row = content.grid_flow(
        row_major=True,
        columns=2,
        even_columns=True,
        even_rows=True,
        align=True,
    )
    for preset, (label, _width, _height) in ASPECT_PRESETS.items():
        operator = aspect_row.operator(
            "mixar.director_set_aspect",
            text=label,
            depress=_aspect_is_active(scene.render, preset),
        )
        operator.preset = preset
    content.label(
        text=f"{scene.render.resolution_x} × {scene.render.resolution_y}",
        icon='IMAGE_PLANE',
    )

    guides = content.row(align=True)
    guides.prop(camera.data, "show_composition_thirds", text="Thirds", toggle=True)
    guides.prop(camera.data, "show_safe_areas", text="Safe Areas", toggle=True)

    timing = _section(layout, "Timing", icon='TIME')
    timing.enabled = editable
    timing.prop(scene.render, "fps", text="Frame Rate")
    timing.prop(state, "beat_seconds", text="Space Keyframes")


def _draw_direction(layout, shot):
    box = _section(layout, "What Happens in the Shot?", icon='TEXT')
    field = box.column()
    field.enabled = shot.state == 'DRAFT'
    draw_multiline_text_input(field, shot, "prompt", min_lines=2, max_lines=4)
    adherence = box.row()
    adherence.enabled = shot.state == 'DRAFT'
    adherence.prop(shot, "guidance_strength", text="Adherence")


class MIXAR_PT_director_shots_popover(Panel):
    """Compact shot and take management for the native Director shell."""

    bl_idname = "MIXAR_PT_director_shots_popover"
    bl_label = "Shots & Takes"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        layout = self.layout
        state = context.scene.mixar_director
        if not state.shots:
            _draw_empty(layout, context.scene)
            return
        _draw_shot_picker(layout, state)
        shot = active_shot(context.scene)
        if shot is None:
            return
        layout.separator(factor=0.45)
        _draw_shot_header(layout, state, shot)
        _draw_session(layout, state, shot)


class MIXAR_PT_director_camera_popover(Panel):
    """Focused camera, composition, timing, and direction controls."""

    bl_idname = "MIXAR_PT_director_camera_popover"
    bl_label = "Camera & Shot"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        layout = self.layout
        state = context.scene.mixar_director
        shot = active_shot(context.scene)
        if shot is None:
            _draw_empty(layout, context.scene)
            return
        _draw_shot_header(layout, state, shot)
        _draw_camera_settings(layout, context.scene, state, shot)
        _draw_direction(layout, shot)


class MIXAR_PT_director_animation_popover(Panel):
    """Blocking-level motion presets for the selected character."""

    bl_idname = "MIXAR_PT_director_animation_popover"
    bl_label = "Animation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        from ...core.animation_presets import ANIMATION_PRESETS

        layout = self.layout
        state = context.scene.mixar_director
        obj = context.active_object
        box = _section(layout, "Animate", icon='ARMATURE_DATA')
        if obj is None or obj.type == 'CAMERA':
            box.label(text="Select a character to animate", icon='INFO')
            return
        box.label(text=obj.name, icon='OBJECT_DATA')
        box.separator(factor=0.4)
        grid = box.grid_flow(
            row_major=True,
            columns=2,
            even_columns=True,
            even_rows=True,
            align=True,
        )
        for key, label, _tooltip in ANIMATION_PRESETS:
            grid.operator("mixar.director_apply_animation", text=label).preset = key
        box.separator(factor=0.4)
        box.prop(state, "animation_seconds", text="Motion Length")
        box.label(text="Keys start at the playhead", icon='TIME')


classes = (
    MIXAR_PT_director_shots_popover,
    MIXAR_PT_director_camera_popover,
    MIXAR_PT_director_animation_popover,
)
