# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Tool Panel

Snapping / Snap Selected / Snap Cursor / Round to Pixels / Align /
Align Rotation sub-section boxes, shown when the `builtin.uv_tool`
toolbar tool is active. Layout matches the Selection panel style:
each section is a `box` with an icon-tagged label header and stacked
controls below — no collapse arrows.
"""

import bpy
from bpy.types import Panel

from mixar.modules.uv_editor.ui.base.panels import snap_base_applies


# Width of the left label column for property rows. Matches the value
# used across the other Mixar UV panels so dropdowns and number inputs
# line up vertically.
_LABEL_FACTOR = 0.4


def _row(col, label_text):
    """Open a `[label][controls]` split row at the standard label factor.

    Returns the right-hand half so the caller can attach its control(s).
    """
    split = col.split(factor=_LABEL_FACTOR, align=True)
    split.label(text=label_text)
    return split


class MIXAR_UV_PT_uv_tool(Panel):
    """Tool panel for the Mixar UV Properties space — shown when the
    `builtin.uv_tool` toolbar tool is active."""
    bl_label = "Tools"
    bl_idname = "MIXAR_UV_PT_uv_tool"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'CHANNELS'
    bl_options = set()
    # Tools (Snapping / Round to Pixels / Align / Align Rotation)
    # sits BELOW any header-tab panel (50) so the artist's selected
    # header context stays on top when both are visible. Only the
    # always-priority panels (UV Sculpt Tools and Annotate,
    # bl_order=-10) sort above the header.
    bl_order = 100

    @classmethod
    def poll(cls, context):
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper

        sima = context.space_data
        if not (sima and sima.mode == 'MIXAR_UV'):
            return False

        obj = context.active_object
        if not (obj and obj.type == 'MESH' and obj.mode == 'EDIT'):
            return False

        # Tool-bar selection takes priority over header selection:
        # whenever `builtin.uv_tool` is active, this panel shows
        # regardless of which header tab is selected.
        area = context.area
        if area:
            with context.temp_override(area=area):
                tool = ToolSelectPanelHelper.tool_active_from_context(context)
                if tool and tool.idname == 'builtin.uv_tool':
                    return True
        return False

    @classmethod
    def msgbus_subscribe(cls, context, subscribe_to):
        """Subscribe to workspace tool changes for auto-refresh.

        Mirrors the pattern used by the other tool-based UV panels so
        switching tools immediately re-evaluates `poll()` and shows /
        hides this panel without needing a manual redraw.
        """
        workspace = context.workspace
        subscribe_to(
            owner=workspace,
            key=(workspace, "tools"),
            options={'PERSISTENT'},
            notify=cls._msgbus_on_workspace_tool_change,
        )

    @staticmethod
    def _msgbus_on_workspace_tool_change():
        for wm in bpy.data.window_managers:
            for window in wm.windows:
                for area in window.screen.areas:
                    if area.type == 'IMAGE_EDITOR':
                        for region in area.regions:
                            region.tag_redraw()

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        layout.separator(factor=0.5)

        tool_settings = context.tool_settings
        wm = context.window_manager
        sima = context.space_data

        self._draw_snapping(layout, tool_settings)
        layout.separator(factor=0.5)

        self._draw_snap_selected(layout)
        layout.separator(factor=0.5)

        self._draw_snap_cursor(layout)
        layout.separator(factor=0.5)

        self._draw_round_to_pixels(layout, sima)
        layout.separator(factor=0.5)

        self._draw_align(layout)
        layout.separator(factor=0.5)

        self._draw_align_rotation(layout, wm)

    # ---------- Snapping ----------

    def _draw_snapping(self, layout, tool_settings):
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Snapping", icon='SNAP_ON')
        col.separator(factor=0.5)

        col.prop(tool_settings, "use_snap_uv", text="Enable Snapping")
        col.separator(factor=0.5)

        col.label(text="Snap Target")
        # `expand=True` on a column stacks the enum items vertically —
        # wrap in a row so Increment / Grid / Vertex sit side by side.
        target_row = col.row(align=True)
        target_row.prop(tool_settings, "snap_uv_element", expand=True)
        col.separator(factor=0.5)

        col.label(text="Snap Base")
        # Snap Base only applies for non-Increment/Grid elements — dim
        # the row visually when it has no effect.
        base_row = col.row(align=True)
        base_row.active = snap_base_applies(tool_settings.snap_uv_element)
        base_row.prop(tool_settings, "snap_target", expand=True)
        col.separator(factor=0.5)

        col.label(text="Affect")
        affect_row = col.row(align=False)
        affect_row.prop(tool_settings, "use_snap_translate",
                        text="Move", toggle=True)
        affect_row.prop(tool_settings, "use_snap_rotate",
                        text="Rotate", toggle=True)
        affect_row.prop(tool_settings, "use_snap_scale",
                        text="Scale", toggle=True)
        col.separator(factor=0.5)

        col.label(text="Rotation Increment")
        rot_row = col.row(align=True)
        rot_row.prop(tool_settings, "snap_angle_increment_2d", text="")
        rot_row.prop(tool_settings, "snap_angle_increment_2d_precision",
                     text="")

    # ---------- Snap Selected ----------

    def _draw_snap_selected(self, layout):
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Snap Selected", icon='PASTEDOWN')
        col.separator(factor=0.5)

        # Two rows of two — the section title already says "Snap
        # Selected", so the short target labels read cleanly.
        row = col.row(align=True)
        row.scale_y = 1.2
        row.operator("mixar.snap_selected",
                     text="Pixels").target = 'PIXELS'
        row.operator("mixar.snap_selected",
                     text="Cursor").target = 'CURSOR'

        row = col.row(align=True)
        row.scale_y = 1.2
        row.operator("mixar.snap_selected",
                     text="Cursor (Offset)").target = 'CURSOR_OFFSET'
        row.operator("mixar.snap_selected",
                     text="Adjacent Unselected").target = 'ADJACENT_UNSELECTED'

    # ---------- Snap Cursor ----------

    def _draw_snap_cursor(self, layout):
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Snap Cursor", icon='PIVOT_CURSOR')
        col.separator(factor=0.5)

        # Single row — the section title already says "Snap Cursor",
        # so the short target labels read cleanly side by side.
        row = col.row(align=True)
        row.scale_y = 1.2
        row.operator("mixar.snap_cursor", text="Pixels").target = 'PIXELS'
        row.operator("mixar.snap_cursor", text="Selected").target = 'SELECTED'
        row.operator("mixar.snap_cursor", text="Origin").target = 'ORIGIN'

    # ---------- Round to Pixels ----------

    def _draw_round_to_pixels(self, layout, sima):
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Round to Pixels", icon='SNAP_GRID')
        col.separator(factor=0.5)

        if sima is None:
            col.label(text="Space data unavailable", icon='ERROR')
            return

        _row(col, "Round to Pixels").prop(sima.uv_editor,
                                          "pixel_round_mode", text="")

    # ---------- Align ----------

    def _draw_align(self, layout):
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Align", icon='ALIGN_JUSTIFY')
        col.separator(factor=0.5)

        # Two rows of three: Straighten group on top, Align group below.
        row = col.row(align=True)
        row.scale_y = 1.2
        row.operator("mixar.align", text="Straighten").axis = 'ALIGN_S'
        row.operator("mixar.align", text="Straighten X").axis = 'ALIGN_T'
        row.operator("mixar.align", text="Straighten Y").axis = 'ALIGN_U'

        col.separator(factor=0.5)

        row = col.row(align=True)
        row.scale_y = 1.2
        row.operator("mixar.align", text="Align Auto").axis = 'ALIGN_AUTO'
        row.operator("mixar.align", text="Align X").axis = 'ALIGN_X'
        row.operator("mixar.align", text="Align Y").axis = 'ALIGN_Y'

    # ---------- Align Rotation ----------

    def _draw_align_rotation(self, layout, wm):
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Align Rotation", icon='CON_ROTLIKE')
        col.separator(factor=0.5)

        p = wm.operator_properties_last("uv.align_rotation")
        if p is None:
            col.label(text="uv.align_rotation properties unavailable",
                      icon='ERROR')
            return

        _row(col, "Method").prop(p, "method", text="")

        # Axis only applies to the Geometry method — dim it for Auto.
        axis_split = col.split(factor=_LABEL_FACTOR, align=True)
        axis_split.label(text="Axis")
        axis_right = axis_split.row(align=True)
        axis_right.enabled = p.method == 'GEOMETRY'
        axis_right.prop(p, "axis", text="")

        col.separator(factor=0.5)
        _row(col, "").prop(p, "correct_aspect", text="Correct Aspect")

        col.separator(factor=0.5)
        run_row = col.row(align=True)
        run_row.scale_y = 1.3
        run_row.operator("mixar.align_rotation", text="Align Rotation",
                         icon='CON_ROTLIKE')


classes = (
    MIXAR_UV_PT_uv_tool,
)
