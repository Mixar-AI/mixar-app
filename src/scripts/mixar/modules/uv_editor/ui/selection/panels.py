# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Selection Panels

Selection panel for the Mixar UV Properties space.
"""

import bpy
from bpy.types import Panel


class MIXAR_UV_PT_selection(Panel):
    """Selection panel for Mixar UV Properties space - Tool-based (no header button)"""
    bl_label = "Selection"
    bl_idname = "MIXAR_UV_PT_selection"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'CHANNELS'
    bl_options = set()
    # Selection sits BELOW any header-tab panel (50) so the artist's
    # selected header context (UV Set / Unwrap / Texel / Layout /
    # Image / Material / Export) stays on top when both are visible.
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
        # whenever a select tool is the active workspace tool, this
        # panel shows — regardless of which header tab is selected.
        # Check if selection tool is active (we're already in IMAGE_EDITOR)
        area = context.area
        if area:
            with context.temp_override(area=area):
                tool = ToolSelectPanelHelper.tool_active_from_context(context)
                if tool and tool.idname in ('builtin.select_box', 'builtin.select_circle', 'builtin.select_lasso'):
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

        # Top padding
        layout.separator(factor=0.5)

        layout.use_property_split = False
        layout.use_property_decorate = False

        # ========== SELECT ALL/NONE/INVERT ==========
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Basic Selection", icon='RESTRICT_SELECT_OFF')
        col.separator(factor=0.5)

        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("uv.select_all", text="All").action = 'SELECT'
        row.operator("uv.select_all", text="None").action = 'DESELECT'
        row.operator("uv.select_all", text="Invert").action = 'INVERT'

        layout.separator(factor=0.5)

        # ========== SELECTION TOOLS ==========
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Selection Tools", icon='HAND')
        col.separator(factor=0.5)

        # Box Select
        row = col.row(align=True)
        row.scale_y = 1.5
        row.operator("mixar.activate_box_select", text="Box Select", icon='BORDERMOVE')

        # Circle Select
        row = col.row(align=True)
        row.scale_y = 1.5
        row.operator("mixar.activate_circle_select", text="Circle Select", icon='MESH_CIRCLE')

        # Lasso Select
        row = col.row(align=True)
        row.scale_y = 1.5
        row.operator("mixar.activate_lasso_select", text="Lasso Select", icon='MOD_CAST')

        layout.separator(factor=0.5)

        # ========== EXPAND/CONTRACT SELECTION ==========
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Expand/Contract", icon='FULLSCREEN_ENTER')
        col.separator(factor=0.5)

        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.select_more", text="More")
        row.operator("mixar.select_less", text="Less")

        layout.separator(factor=0.5)

        # ========== SELECT SIMILAR & LINKED ==========
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Similar & Linked", icon='LINKED')
        col.separator(factor=0.5)

        # Get select mode to determine which buttons to show
        tool_settings = context.tool_settings
        use_island_mode = tool_settings.use_uv_select_island

        if tool_settings.use_uv_select_sync:
            # Sync with mesh select mode
            is_vert_mode, is_edge_mode, is_face_mode = tool_settings.mesh_select_mode
        else:
            # Use UV select mode
            uv_select_mode = tool_settings.uv_select_mode
            is_vert_mode = uv_select_mode == 'VERTEX'
            is_edge_mode = uv_select_mode == 'EDGE'
            is_face_mode = uv_select_mode == 'FACE'

        # Show buttons based on select mode
        row = col.row(align=True)
        row.scale_y = 1.2

        if use_island_mode:
            # Island mode: AREA, AREA_3D, FACE
            row.operator("mixar.select_similar", text="Area").type = 'AREA'
            row.operator("mixar.select_similar", text="Area 3D").type = 'AREA_3D'
            row.operator("mixar.select_similar", text="Faces in Island").type = 'FACE'
        elif is_face_mode:
            # Face mode: AREA, AREA_3D, MATERIAL, OBJECT, SIDES, WINDING.
            # Six buttons split across two rows (3 + 3) so each label has
            # room to render without truncation.
            row.operator("mixar.select_similar", text="Area").type = 'AREA'
            row.operator("mixar.select_similar", text="Area 3D").type = 'AREA_3D'
            row.operator("mixar.select_similar", text="Material").type = 'MATERIAL'

            row = col.row(align=True)
            row.scale_y = 1.2
            row.operator("mixar.select_similar", text="Object").type = 'OBJECT'
            row.operator("mixar.select_similar", text="Sides").type = 'SIDES'
            row.operator("mixar.select_similar", text="Winding").type = 'WINDING'
        elif is_edge_mode:
            # Edge mode: LENGTH, LENGTH_3D, PIN
            row.operator("mixar.select_similar", text="Length").type = 'LENGTH'
            row.operator("mixar.select_similar", text="Length 3D").type = 'LENGTH_3D'
            row.operator("mixar.select_similar", text="Pin").type = 'PIN'
        else:
            # Vertex mode: PIN
            row.operator("mixar.select_similar", text="Pin").type = 'PIN'

        row = col.row(align=True)
        row.scale_y = 1.2
        row.operator("mixar.select_linked", text="Linked")
        row.operator("mixar.shortest_path_select", text="Shortest Path")

        layout.separator(factor=0.5)

        # ========== SPECIAL SELECTION ==========
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Special Selection", icon='OUTLINER_OB_LATTICE')
        col.separator(factor=0.5)

        # Select Pinned only operates in vertex select mode — disable
        # the row in edge/face/island modes so its inactive state is
        # visually obvious instead of failing silently on click.
        pin_row = col.row(align=True)
        pin_row.enabled = is_vert_mode
        pin_row.operator("uv.select_pinned", text="Select Pinned", icon='PINNED')

        col.operator("uv.select_split", text="Select Split", icon='SNAP_VERTEX')
        col.operator("uv.select_overlap", text="Select Overlap", icon='SELECT_INTERSECT')


classes = (
    MIXAR_UV_PT_selection,
)
