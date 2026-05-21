# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Layout Panel

Layout panel: Selection-style sub-section boxes for Pack Islands,
Average Islands Scale, and Minimize Stretch. When Pack To = Custom
Region, a Set Custom Region button is rendered inside the Pack Islands
box (use_uv_custom_region is auto-enabled in that case).

All rows in this panel use a fixed `split` factor for label / control
alignment so that checkboxes, dropdowns, and number inputs line up in
the same right-hand column.
"""

import bpy
from bpy.types import Panel

from mixar.modules.uv_editor.ui.base.panels import poll_header_panel


# Width of the left label column. Picked so labels like "Rotation Method"
# and "Lock Method" fit comfortably while leaving the bulk of each row
# for the control on the right.
_LABEL_FACTOR = 0.4


# Module-level "first draw" sentinels. Mixar overrides Blender's defaults
# for `pin` (Lock Pinned Islands) and `pin_method` (the "All" item, whose
# enum identifier is 'LOCKED') on first draw of the panel; subsequent
# draws respect whatever the user set, so explicit toggles aren't
# overridden.
_PACK_DEFAULTS_INITIALIZED = False
_CUSTOM_REGION_DEFAULT_INITIALIZED = False


def _ensure_pack_defaults(op_props):
    global _PACK_DEFAULTS_INITIALIZED
    if _PACK_DEFAULTS_INITIALIZED or op_props is None:
        return
    op_props.pin = True
    op_props.pin_method = 'LOCKED'
    _PACK_DEFAULTS_INITIALIZED = True


def _ensure_custom_region_default():
    """Defer setting `tool_settings.use_uv_custom_region = True` to a
    one-shot timer.

    Panel `draw()` runs in a read-only Blender context — writing to
    Scene-owned data (ToolSettings) raises AttributeError there. Timers
    fire outside that context, so the write is safe.
    """
    global _CUSTOM_REGION_DEFAULT_INITIALIZED
    if _CUSTOM_REGION_DEFAULT_INITIALIZED:
        return
    _CUSTOM_REGION_DEFAULT_INITIALIZED = True

    def _apply():
        scene = bpy.context.scene
        if scene is not None:
            scene.tool_settings.use_uv_custom_region = True
        return None  # one-shot — don't reschedule

    try:
        bpy.app.timers.register(_apply, first_interval=0.0)
    except Exception:
        pass


def _row(col, label_text):
    """Open a `[label][controls]` split row at the standard label factor.

    Returns the right-hand half so the caller can attach its control(s).
    Pass an empty `label_text` to leave a blank gutter — useful for
    checkboxes that should align under other rows' controls.
    """
    split = col.split(factor=_LABEL_FACTOR, align=True)
    split.label(text=label_text)
    return split


def _prop_row_if_exists(col, owner, label_text, prop_name):
    if not hasattr(owner, prop_name):
        col.label(text=f"{label_text} unavailable", icon='ERROR')
        return
    _row(col, label_text).prop(owner, prop_name, text="")


class MIXAR_UV_PT_pack_islands(Panel):
    """Layout panel for the Mixar UV Properties space."""
    bl_label = "Layout"
    bl_idname = "MIXAR_UV_PT_pack_islands"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'CHANNELS'
    bl_options = set()
    # Header-driven panels sort in the middle band (above Selection /
    # UV Tool / Functions / Transform = 100, below UV Sculpt Tools /
    # Annotate = -10).
    bl_order = 50

    @classmethod
    def poll(cls, context):
        return poll_header_panel(context, 'PACK_ISLANDS')

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        layout.use_property_split = False
        layout.use_property_decorate = False
        layout.separator(factor=0.5)

        op_props = wm.operator_properties_last("uv.pack_islands")
        _ensure_pack_defaults(op_props)

        # Pack Islands properties — when Pack To = Custom Region the
        # Set Custom Region button is rendered inside this same box.
        self._draw_pack_islands_props(layout, op_props)

        # Pack Islands run button (full-width, primary action).
        layout.separator(factor=0.5)
        run_row = layout.row(align=True)
        run_row.scale_y = 1.5
        run_row.operator("mixar.pack_islands", text="Pack Islands",
                         icon='PACKAGE')

        layout.separator(factor=0.5)
        self._draw_average_scale(layout, wm)

        layout.separator(factor=0.5)
        self._draw_minimize_stretch(layout, wm)

        layout.separator(factor=0.5)
        self._draw_arrange_islands(layout, wm)

    # ---------- Pack Islands properties ----------

    def _draw_pack_islands_props(self, layout, p):
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Pack Islands", icon='PACKAGE')
        col.separator(factor=0.5)

        if p is None:
            col.label(text="uv.pack_islands properties unavailable",
                      icon='ERROR')
            return

        # Shape Method
        _row(col, "Shape Method").prop(p, "shape_method", text="")

        # Scale + Rotate inline checkboxes (in the right column).
        right = _row(col, "")
        sub = right.row(align=True)
        sub.prop(p, "scale")
        sub.prop(p, "rotate")

        # Rotation Method (disabled when Rotate is off).
        rot_split = col.split(factor=_LABEL_FACTOR, align=True)
        rot_split.label(text="Rotation Method")
        rot_right = rot_split.row(align=True)
        rot_right.enabled = p.rotate
        rot_right.prop(p, "rotate_method", text="")

        # Margin: dropdown + numeric on one row in the right column.
        margin_right = _row(col, "Margin")
        m_row = margin_right.row(align=True)
        m_row.prop(p, "margin_method", text="")
        m_row.prop(p, "margin", text="")

        # Lock Pinned Islands toggle in the right column.
        _row(col, "").prop(p, "pin", text="Lock Pinned Islands")

        # Lock Method (disabled when Lock Pinned is off).
        lock_split = col.split(factor=_LABEL_FACTOR, align=True)
        lock_split.label(text="Lock Method")
        lock_right = lock_split.row(align=True)
        lock_right.enabled = p.pin
        lock_right.prop(p, "pin_method", text="")

        # Merge Overlapping toggle in the right column.
        _row(col, "").prop(p, "merge_overlap", text="Merge Overlapping")

        # Pack To dropdown.
        _row(col, "Pack To").prop(p, "udim_source", text="")

        # Set Custom Region button — only when Pack To = Custom Region.
        # `use_uv_custom_region` is enabled automatically by the timer
        # below, so no separate toggle is shown.
        if p.udim_source == 'CUSTOM_REGION':
            _ensure_custom_region_default()
            col.separator(factor=0.5)
            run_row = col.row(align=True)
            run_row.scale_y = 1.3
            run_row.operator("mixar.custom_region_set",
                             text="Set Custom Region", icon='SELECT_SET')

    # ---------- Average Islands Scale sub-section ----------

    def _draw_average_scale(self, layout, wm):
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Average Islands Scale", icon='SNAP_FACE_CENTER')
        col.separator(factor=0.5)

        avg_props = wm.operator_properties_last("uv.average_islands_scale")
        if avg_props is not None:
            # Non-Uniform + Shear span the full width (no left gutter).
            sub = col.row(align=True)
            sub.prop(avg_props, "scale_uv", text="Non-Uniform")
            sub.prop(avg_props, "shear", text="Shear")

        col.separator(factor=0.5)
        run_row = col.row(align=True)
        run_row.scale_y = 1.3
        run_row.operator("mixar.average_islands_scale",
                         text="Average Islands Scale",
                         icon='SNAP_FACE_CENTER')

    # ---------- Minimize Stretch sub-section ----------

    def _draw_minimize_stretch(self, layout, wm):
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Minimize Stretch", icon='MESH_GRID')
        col.separator(factor=0.5)

        stretch_props = wm.operator_properties_last("uv.minimize_stretch")
        if stretch_props is None:
            col.label(text="uv.minimize_stretch properties unavailable",
                      icon='ERROR')
            return

        # Fill Holes — full-width checkbox.
        col.prop(stretch_props, "fill_holes", text="Fill Holes")

        # Blend and Iterations split the row 50/50 — each `[label][input]`
        # pair occupies half the line.
        halves = col.split(factor=0.5, align=True)
        b_pair = halves.split(factor=0.4, align=True)
        b_pair.label(text="Blend")
        b_pair.prop(stretch_props, "blend", text="")
        i_pair = halves.split(factor=0.5, align=True)
        i_pair.label(text="Iterations")
        i_pair.prop(stretch_props, "iterations", text="")

        col.separator(factor=0.5)
        run_row = col.row(align=True)
        run_row.scale_y = 1.3
        run_row.operator("mixar.minimize_stretch", text="Minimize Stretch",
                         icon='MESH_GRID')

    # ---------- Arrange Islands sub-section ----------

    def _draw_arrange_islands(self, layout, wm):
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Arrange Islands", icon='SNAP_GRID')
        col.separator(factor=0.5)

        p = wm.operator_properties_last("uv.arrange_islands")
        if p is None:
            col.label(text="uv.arrange_islands properties unavailable",
                      icon='ERROR')
            return

        _prop_row_if_exists(col, p, "Initial Position", "initial_position")
        _prop_row_if_exists(col, p, "Axis", "axis")
        _prop_row_if_exists(col, p, "Align", "align")
        _prop_row_if_exists(col, p, "Order", "order")
        _prop_row_if_exists(col, p, "Margin", "margin")

        col.separator(factor=0.5)
        run_row = col.row(align=True)
        run_row.scale_y = 1.3
        run_row.operator("mixar.arrange_islands", text="Apply Arrangement",
                         icon='SNAP_GRID')


classes = (
    MIXAR_UV_PT_pack_islands,
)
