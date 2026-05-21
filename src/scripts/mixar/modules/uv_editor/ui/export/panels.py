# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Export Panels

UV Export panel for the Mixar UV Properties space.
"""

from bpy.types import Panel

from mixar.modules.uv_editor.ui.base.panels import poll_header_panel


# Width of the left label column. Matches the Texel Density / Pack Islands
# sub-section split factor so all panels in the Mixar UV Properties space
# line up the same way.
_LABEL_FACTOR = 0.4


def _row(col, label_text):
    """Open a `[label][controls]` split row at the standard label factor.

    Pass an empty `label_text` to leave a blank gutter — useful for
    checkboxes that should align under other rows' controls.
    """
    split = col.split(factor=_LABEL_FACTOR, align=True)
    split.label(text=label_text)
    return split


class MIXAR_UV_PT_export(Panel):
    """UV Export panel for Mixar UV Properties space"""
    bl_label = "Export"
    bl_idname = "MIXAR_UV_PT_export"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'CHANNELS'
    bl_options = set()
    # Header-driven panels sort in the middle band (above Selection /
    # UV Tool / Functions / Transform = 100, below UV Sculpt Tools /
    # Annotate = -10).
    bl_order = 50

    @classmethod
    def poll(cls, context):
        return poll_header_panel(context, 'EXPORT', requires_edit=True)

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        layout.use_property_split = False
        layout.use_property_decorate = False
        layout.separator(factor=0.5)

        if not hasattr(wm, 'mixar_uv_ui'):
            layout.label(text="UV UI not initialized", icon='ERROR')
            return

        op_props = wm.operator_properties_last("uv.export_layout")

        box = layout.box()
        col = box.column(align=True)
        col.label(text="Export Settings", icon='EXPORT')
        col.separator(factor=0.5)

        if op_props is None:
            col.label(text="uv.export_layout properties unavailable",
                      icon='ERROR')
            return

        _row(col, "Format").prop(op_props, "mode", text="")
        _row(col, "Export Tiles").prop(op_props, "export_tiles", text="")

        # Size is a 2-component vector — render the two components on
        # one row so X and Y sit side by side.
        size_split = col.split(factor=_LABEL_FACTOR, align=True)
        size_split.label(text="Size")
        size_row = size_split.row(align=True)
        size_row.prop(op_props, "size", index=0, text="")
        size_row.prop(op_props, "size", index=1, text="")

        _row(col, "Fill Opacity").prop(op_props, "opacity", text="")

        # All UVs + Modified share a single row in the right gutter.
        flags_split = col.split(factor=_LABEL_FACTOR, align=True)
        flags_split.label(text="")
        flags_row = flags_split.row(align=True)
        flags_row.prop(op_props, "export_all", text="All UVs")
        flags_row.prop(op_props, "modified", text="Modified")

        col.separator(factor=0.5)
        run_row = col.row(align=True)
        run_row.scale_y = 1.5
        run_row.operator("mixar.export_uv_layout", text="Export UV Layout",
                         icon='EXPORT')


classes = (
    MIXAR_UV_PT_export,
)
