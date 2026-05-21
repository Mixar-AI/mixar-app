# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Functions Panels

UV Functions panel for the Mixar UV Properties space.
"""

import bpy
from bpy.types import Panel


class MIXAR_UV_PT_functions(Panel):
    """UV Functions panel for Mixar UV Properties space - Tool-based (no header button)"""
    bl_label = "Functions"
    bl_idname = "MIXAR_UV_PT_functions"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'CHANNELS'
    bl_options = set()
    # Functions sits BELOW any header-tab panel (50) so the artist's
    # selected header context stays on top when both are visible.
    # Only the always-priority panels (UV Sculpt Tools and Annotate,
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
        # whenever `builtin.uv_functions` is active, this panel shows
        # regardless of which header tab is selected.
        # Check if UV functions tool is active (we're already in IMAGE_EDITOR)
        area = context.area
        if area:
            with context.temp_override(area=area):
                tool = ToolSelectPanelHelper.tool_active_from_context(context)
                if tool and tool.idname == 'builtin.uv_functions':
                    return True
        return False

    @classmethod
    def msgbus_subscribe(cls, context, subscribe_to):
        """Subscribe to workspace tool changes for auto-refresh.

        This ensures the panel refreshes immediately when tools change,
        regardless of when the panel area was created (startup or manual).
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
        """Callback when workspace tools change - refresh all IMAGE_EDITOR areas."""
        for wm in bpy.data.window_managers:
            for window in wm.windows:
                for area in window.screen.areas:
                    if area.type == 'IMAGE_EDITOR':
                        for region in area.regions:
                            region.tag_redraw()

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        # Get UI state
        if not hasattr(wm, 'mixar_uv_ui'):
            layout.label(text="UV UI not initialized", icon='ERROR')
            return

        uv_ui = wm.mixar_uv_ui

        # Top padding
        layout.separator(factor=0.5)

        layout.use_property_split = False
        layout.use_property_decorate = False

        # ========== SEAM OPERATIONS ==========
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Seam", icon='EDGE_SEAM')
        col.separator(factor=0.5)

        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.mark_seam", text="Mark Seam")
        row.operator("mixar.clear_seam", text="Clear Seam")

        col.separator(factor=0.3)

        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.seams_from_islands", text="Seam from Islands")

        layout.separator(factor=0.5)

        # ========== STITCH OPERATIONS ==========
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Stitch", icon='AUTOMERGE_ON')
        col.separator(factor=0.5)

        # Get operator properties
        op_props = wm.operator_properties_last("uv.stitch")

        # Compress all seven Stitch options into four rows: Mode,
        # Use Limit + value, Snap Islands + Midpoint Snap, Clear Seams +
        # Static Island.

        # Line 1 — Mode
        col.prop(op_props, "mode", text="Mode")

        col.separator(factor=0.3)

        # Line 2 — Use Limit checkbox paired with its distance value.
        # The distance field is disabled when the toggle is off.
        row = col.row(align=True)
        row.prop(op_props, "use_limit", text="Use Limit")
        sub = row.row(align=True)
        sub.active = op_props.use_limit
        sub.prop(op_props, "limit", text="")

        col.separator(factor=0.3)

        # Line 3 — Snap Islands + Midpoint Snap
        row = col.row(align=True)
        row.prop(op_props, "snap_islands", text="Snap Islands")
        row.prop(op_props, "midpoint_snap", text="Midpoint Snap")

        col.separator(factor=0.3)

        # Line 4 — Clear Seams + Static Island
        row = col.row(align=True)
        row.prop(op_props, "clear_seams", text="Clear Seams")
        row.prop(op_props, "static_island", text="Static Island")

        col.separator()

        # Stitch button
        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.stitch", text="Stitch", icon='AUTOMERGE_ON')

        layout.separator(factor=0.5)

        # ========== MERGE OPERATIONS ==========
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Merge", icon='AUTOMERGE_ON')
        col.separator(factor=0.5)

        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.weld", text="At Center")
        row.operator("mixar.merge_at_cursor", text="At Cursor")

        col.separator(factor=0.3)

        # Get operator properties for remove_doubles
        op_props_merge = wm.operator_properties_last("uv.remove_doubles")
        col.prop(op_props_merge, "threshold", text="Distance")

        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.remove_doubles", text="By Distance")

        layout.separator(factor=0.5)

        # ========== PIN OPERATIONS ==========
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Pin", icon='PINNED')
        col.separator(factor=0.5)

        # All three pin operations on a single row.
        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.pin", text="Pin")
        row.operator("mixar.unpin", text="Unpin")
        row.operator("mixar.invert_pin", text="Invert")

        layout.separator(factor=0.5)

        # ========== HIDE OPERATIONS ==========
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Hide", icon='HIDE_OFF')
        col.separator(factor=0.5)

        # All three hide operations on a single row — the section title
        # already says "Hide", so the short labels read cleanly.
        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.hide_selected", text="Selected")
        row.operator("mixar.reveal", text="Reveal")
        row.operator("mixar.hide_unselected", text="Unselected")

        layout.separator(factor=0.5)

        # ========== COPY/PASTE OPERATIONS ==========
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Copy/Paste", icon='COPY_ID')
        col.separator(factor=0.5)

        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.copy_uvs", text="Copy UVs", icon='COPYDOWN')
        row.operator("mixar.paste_uvs", text="Paste UVs", icon='PASTEDOWN')


classes = (
    MIXAR_UV_PT_functions,
)
