# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Unwrap Panel

Combined Unwrap + Project panel: shows two Selection-style sub-section
boxes — "Unwrap" (method dropdown + properties + Unwrap button) and
"Project" (type dropdown + properties + Project button) — under a single
panel header. Replaces the previous separate Projection panel.
"""

import bpy
from bpy.types import Panel

from mixar.modules.uv_editor.ui.base.panels import poll_header_panel


# Width of the left label column. Matches the Texel Density / UV Set /
# Layout panels so labels line up across the sidebar.
_LABEL_FACTOR = 0.4


def _row(col, label_text):
    """`[label][control]` split row at the standard label factor.

    Labels are left-aligned inside the split's first cell — same pattern
    the Texel Density panel uses to produce its flush-left rows. The
    returned right-hand cell takes the caller's control(s)."""
    split = col.split(factor=_LABEL_FACTOR, align=True)
    split.label(text=label_text)
    return split


class MIXAR_UV_PT_unwrap(Panel):
    """Combined Unwrap + Project panel for the Mixar UV Properties space."""
    bl_label = "Unwrap"
    bl_idname = "MIXAR_UV_PT_unwrap"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'CHANNELS'
    bl_options = set()
    # Header-driven panels sort in the middle band (above Selection /
    # UV Tool / Functions / Transform = 100, below UV Sculpt Tools /
    # Annotate = -10).
    bl_order = 50

    @classmethod
    def poll(cls, context):
        return poll_header_panel(context, 'UNWRAP', requires_edit=True)

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        if not hasattr(wm, 'mixar_uv_ui'):
            layout.label(text="UV UI not initialized", icon='ERROR')
            return

        layout.use_property_split = False
        layout.use_property_decorate = False
        layout.separator(factor=0.5)

        uv_ui = wm.mixar_uv_ui

        # Live Unwrap toggle — pinned to the top of the panel above the
        # Unwrap and Project sections. Mirrors Blender's UV menu entry
        # (`tool_settings.use_edge_path_live_unwrap`).
        scene = context.scene
        if scene is not None:
            top = layout.column(align=True)
            top.use_property_split = False
            top.prop(scene.tool_settings, "use_edge_path_live_unwrap",
                     text="Live Unwrap")
            layout.separator(factor=0.5)

        self._draw_unwrap_section(layout, wm, uv_ui)
        layout.separator(factor=0.5)
        self._draw_project_section(layout, wm, uv_ui)

    # ---------- Unwrap section ----------

    def _draw_unwrap_section(self, layout, wm, uv_ui):
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Unwrap", icon='UV_SYNC_SELECT')
        col.separator(factor=0.5)

        _row(col, "Method").prop(uv_ui, "unwrap_method", text="")

        method = uv_ui.unwrap_method
        if method == 'SMART_PROJECT':
            self._draw_smart_project_props(col, wm)
        else:
            self._draw_unwrap_props(col, wm, method)

        col.separator(factor=0.5)
        run_row = col.row(align=True)
        run_row.scale_y = 1.5
        run_row.operator("mixar.unwrap", text="Unwrap", icon='UV_SYNC_SELECT')

    @staticmethod
    def _draw_unwrap_props(col, wm, method):
        op_props = wm.operator_properties_last("uv.unwrap")
        if op_props is None:
            col.label(text="uv.unwrap properties unavailable", icon='ERROR')
            return

        # Keep the operator's `method` enum aligned with the dropdown so that
        # Blender's tool-settings sync (live unwrap, etc.) stays in step.
        if op_props.method != method:
            op_props.method = method

        # Bool toggles laid out two-per-row (full-width row for the
        # widow toggle when there's an odd count) so the panel stays
        # compact instead of stacking every checkbox on its own line.
        if method == 'MINIMUM_STRETCH':
            _row(col, "Iterations").prop(op_props, "iterations", text="")
            if op_props.use_weights:
                _row(col, "Weight Group").prop(op_props, "weight_group", text="")
                _row(col, "Weight Factor").prop(op_props, "weight_factor", text="")

            row = col.row(align=True)
            row.prop(op_props, "no_flip")
            row.prop(op_props, "use_weights", text="Importance Weights")
            row = col.row(align=True)
            row.prop(op_props, "correct_aspect")
            row.prop(op_props, "use_subsurf_data",
                     text="Subdivision Surface")
        else:
            row = col.row(align=True)
            row.prop(op_props, "fill_holes")
            row.prop(op_props, "correct_aspect")
            col.prop(op_props, "use_subsurf_data",
                     text="Use Subdivision Surface")

        _row(col, "Margin Method").prop(op_props, "margin_method", text="")
        _row(col, "Margin").prop(op_props, "margin", text="")

    @staticmethod
    def _draw_smart_project_props(col, wm):
        op_props = wm.operator_properties_last("uv.smart_project")
        if op_props is None:
            col.label(text="uv.smart_project properties unavailable", icon='ERROR')
            return

        _row(col, "Angle Limit").prop(op_props, "angle_limit", text="")
        _row(col, "Margin Method").prop(op_props, "margin_method", text="")
        _row(col, "Rotate Method").prop(op_props, "rotate_method", text="")
        _row(col, "Island Margin").prop(op_props, "island_margin", text="")
        _row(col, "Area Weight").prop(op_props, "area_weight", text="")
        # Two bool toggles share a single row so the section stays tight.
        row = col.row(align=True)
        row.prop(op_props, "correct_aspect")
        row.prop(op_props, "scale_to_bounds")

    # ---------- Project section ----------

    def _draw_project_section(self, layout, wm, uv_ui):
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Project", icon='MOD_UVPROJECT')
        col.separator(factor=0.5)

        _row(col, "Type").prop(uv_ui, "projection_type", text="")

        ptype = uv_ui.projection_type
        drawer = _PROJECTION_DRAWERS.get(ptype)
        if drawer is not None:
            drawer(col, wm)

        col.separator(factor=0.5)
        run_row = col.row(align=True)
        run_row.scale_y = 1.5
        run_row.operator("mixar.project", text="Project", icon='MOD_UVPROJECT')


# ---------- Project drawers (one per projection type) ----------

def _draw_cube(col, wm):
    p = wm.operator_properties_last("uv.cube_project")
    if p is None:
        col.label(text="uv.cube_project properties unavailable", icon='ERROR')
        return
    _row(col, "Cube Size").prop(p, "cube_size", text="")
    _bool_row(col, p, ("correct_aspect", "clip_to_bounds", "scale_to_bounds"))


def _draw_cylinder(col, wm):
    p = wm.operator_properties_last("uv.cylinder_project")
    if p is None:
        col.label(text="uv.cylinder_project properties unavailable", icon='ERROR')
        return
    _row(col, "Direction").prop(p, "direction", text="")
    _row(col, "Align").prop(p, "align", text="")
    _row(col, "Pole").prop(p, "pole", text="")
    # Radius sits with the rest of the labelled inputs, above the
    # boolean row. Seam folds in as `Preserve Seam` alongside the other
    # toggles so all four bools share a 2x2 grid instead of an awkward
    # labelled checkbox + 3-toggle row.
    _row(col, "Radius").prop(p, "radius", text="")
    row1 = col.row(align=True)
    row1.prop(p, "seam", text="Preserve Seam")
    row1.prop(p, "correct_aspect")
    row2 = col.row(align=True)
    row2.prop(p, "clip_to_bounds")
    row2.prop(p, "scale_to_bounds")


def _draw_sphere(col, wm):
    p = wm.operator_properties_last("uv.sphere_project")
    if p is None:
        col.label(text="uv.sphere_project properties unavailable", icon='ERROR')
        return
    _row(col, "Direction").prop(p, "direction", text="")
    _row(col, "Align").prop(p, "align", text="")
    _row(col, "Pole").prop(p, "pole", text="")
    # Same 2x2 toggle grid as the cylinder projection: Preserve Seam
    # joins the other three booleans instead of getting its own row.
    row1 = col.row(align=True)
    row1.prop(p, "seam", text="Preserve Seam")
    row1.prop(p, "correct_aspect")
    row2 = col.row(align=True)
    row2.prop(p, "clip_to_bounds")
    row2.prop(p, "scale_to_bounds")


def _draw_camera(col, wm):
    p = wm.operator_properties_last("mixar.camera_project")
    if p is None:
        col.label(text="mixar.camera_project properties unavailable", icon='ERROR')
        return
    _row(col, "Scale").prop(p, "scale", text="")
    _bool_row(col, p, ("correct_aspect",))


def _draw_normal(col, wm):
    p = wm.operator_properties_last("mixar.normal_project")
    if p is None:
        col.label(text="mixar.normal_project properties unavailable", icon='ERROR')
        return
    _row(col, "Scale").prop(p, "scale", text="")
    _bool_row(col, p, ("correct_aspect",))


def _draw_planar(col, wm):
    p = wm.operator_properties_last("mixar.planar_project")
    if p is None:
        col.label(text="mixar.planar_project properties unavailable", icon='ERROR')
        return
    _row(col, "Axis").prop(p, "axis", text="")
    _row(col, "Scale").prop(p, "scale", text="")
    _bool_row(col, p, ("correct_aspect", "center_uvs"))


def _bool_row(col, props, names):
    """Inline checkboxes laid out flush left across one row."""
    row = col.row(align=True)
    for name in names:
        row.prop(props, name)


_PROJECTION_DRAWERS = {
    'CUBE': _draw_cube,
    'CYLINDER': _draw_cylinder,
    'SPHERE': _draw_sphere,
    'CAMERA': _draw_camera,
    'NORMAL': _draw_normal,
    'PLANAR': _draw_planar,
}


classes = (
    MIXAR_UV_PT_unwrap,
)
