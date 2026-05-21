# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Tools Panels

UV Sculpt Tools panel for the Mixar UV Properties space.
"""

import bpy
from bpy.types import Panel


# Width of the left label column inside Properties rows. Matches the
# value used in the Texel Density / Selection panels so labels line up
# vertically with the controls.
_LABEL_FACTOR = 0.4


def _labelled_prop(col, owner, prop_name, label):
    """Draw a `[label][control]` row with a left-aligned label column.

    Mirrors the helper in `texel_density.texel.ui` so Tool Properties
    rows share the same look as Texel Density / Selection sub-sections.
    """
    split = col.split(factor=_LABEL_FACTOR, align=True)
    split.label(text=label)
    split.prop(owner, prop_name, text="")


def draw_collapsible_header(layout, ui_state, prop_name, label, icon='NONE'):
    """Draw a collapsible section header with arrow toggle.

    Args:
        layout: The layout to draw in (typically a box)
        ui_state: The MixarUVUIState property group
        prop_name: Name of the BoolProperty controlling expansion
        label: Text label for the section
        icon: Optional icon for the label

    Returns:
        bool: Whether the section is expanded
    """
    is_expanded = getattr(ui_state, prop_name)

    header_row = layout.row(align=True)
    header_row.scale_y = 1.3

    collapse_icon = 'DOWNARROW_HLT' if is_expanded else 'RIGHTARROW'
    header_row.prop(ui_state, prop_name, text="", icon=collapse_icon, emboss=False)
    header_row.label(text=label, icon=icon)

    return is_expanded


class MIXAR_UV_PT_tools(Panel):
    """UV Sculpt Tools panel for Mixar UV Properties space - Tool-based (no header button)"""
    bl_label = "UV Sculpt Tools"
    bl_idname = "MIXAR_UV_PT_tools"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'CHANNELS'
    bl_options = set()
    # UV Sculpt Tools always sits at the very top of the sidebar so
    # brush properties (Size / Strength / Falloff) stay visible while
    # the artist sculpts — even with a header tab also selected.
    # `bl_order=-10` keeps it above header panels (50) and the other
    # tool panels (Selection / UV Tool / Functions / Transform = 100).
    bl_order = -10

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
        # whenever a UV sculpt tool is active, this panel shows
        # regardless of which header tab is selected.
        # Check if UV sculpt tool is active (we're already in IMAGE_EDITOR)
        uv_sculpt_tools = ('sculpt.uv_sculpt_grab', 'sculpt.uv_sculpt_relax', 'sculpt.uv_sculpt_pinch', 'builtin.rip_region')

        area = context.area
        if area:
            with context.temp_override(area=area):
                tool = ToolSelectPanelHelper.tool_active_from_context(context)
                if tool and tool.idname in uv_sculpt_tools:
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
        tool_settings = context.tool_settings

        layout.separator(factor=0.5)

        # ========== VIEW BUTTONS - MOVED TO TOOL SETTINGS HEADER ==========
        # Previously here: Frame Selected, Frame All, Center View to Cursor
        # Now in IMAGE_HT_tool_header for better accessibility

        # Get active tool from current IMAGE_EDITOR context
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper

        tool = ToolSelectPanelHelper.tool_active_from_context(context)
        active_tool_id = tool.idname if tool else None

        # Match the brush / rip glyphs the IMAGE_EDITOR toolbar uses for
        # the same tools (`brush.uv_sculpt.*` + `ops.mesh.rip`) by
        # loading the .dat icon values directly — the standard `icon=`
        # enum has no equivalents for the UV-sculpt brush set.
        _icon_handle = ToolSelectPanelHelper._icon_value_from_icon_handle
        icon_grab = _icon_handle("brush.uv_sculpt.grab")
        icon_relax = _icon_handle("brush.uv_sculpt.relax")
        icon_pinch = _icon_handle("brush.uv_sculpt.pinch")
        icon_rip = _icon_handle("ops.mesh.rip")

        # ---- Tool selection buttons (no box wrapper, no header) ----
        tools_col = layout.column(align=True)

        row = tools_col.row(align=True)
        row.scale_y = 1.5
        row.operator("mixar.activate_uv_sculpt_grab",
                     text="Grab", icon_value=icon_grab,
                     depress=(active_tool_id == 'sculpt.uv_sculpt_grab'))

        row = tools_col.row(align=True)
        row.scale_y = 1.5
        row.operator("mixar.activate_uv_sculpt_relax",
                     text="Relax", icon_value=icon_relax,
                     depress=(active_tool_id == 'sculpt.uv_sculpt_relax'))

        row = tools_col.row(align=True)
        row.scale_y = 1.5
        row.operator("mixar.activate_uv_sculpt_pinch",
                     text="Pinch", icon_value=icon_pinch,
                     depress=(active_tool_id == 'sculpt.uv_sculpt_pinch'))

        row = tools_col.row(align=True)
        row.scale_y = 1.5
        row.operator("mixar.activate_rip_region",
                     text="Rip Region", icon_value=icon_rip,
                     depress=(active_tool_id == 'builtin.rip_region'))

        layout.separator(factor=0.5)

        # ========== TOOL PROPERTIES (only if UV sculpt tool is active) ==========
        sculpt_tool_ids = ('sculpt.uv_sculpt_grab',
                           'sculpt.uv_sculpt_relax',
                           'sculpt.uv_sculpt_pinch')
        active_tool_id = tool.idname if tool else None
        if active_tool_id not in sculpt_tool_ids:
            # Rip Region has no panel-level settings — render nothing
            # extra so the panel ends cleanly after the tool buttons.
            if active_tool_id == 'builtin.rip_region':
                return
            # No UV sculpt tool active, show info message
            info_box = layout.box()
            info_col = info_box.column(align=True)
            info_col.label(text="Select a tool above to", icon='INFO')
            info_col.label(text="see its properties")
            return

        layout.use_property_split = False
        layout.use_property_decorate = False

        wm = context.window_manager
        uv_ui = wm.mixar_uv_ui
        uv_sculpt = tool_settings.uv_sculpt

        tool_name = {
            'sculpt.uv_sculpt_grab': 'Grab',
            'sculpt.uv_sculpt_relax': 'Relax',
            'sculpt.uv_sculpt_pinch': 'Pinch',
        }.get(tool.idname, 'Tool')

        # Header with tool name — no icon, the toolbar buttons above
        # already carry the brush glyphs.
        box = layout.box()
        row = box.row()
        row.label(text=f"{tool_name} Properties")

        col = box.column(align=True)
        col.separator(factor=0.5)

        # Size and Strength — left-aligned label column to match the
        # Texel Density panel layout.
        _labelled_prop(col, uv_sculpt, "size", "Size")
        _labelled_prop(col, uv_sculpt, "strength", "Strength")

        # Options merged into the same Properties box (no separate
        # Options collapsible). Lock Borders and Sculpt All Islands
        # share a single row so they read as paired toggles; Relax
        # Method drops below.
        col.separator(factor=0.5)
        toggles = col.row(align=True)
        toggles.prop(tool_settings, "uv_sculpt_lock_borders", text="Lock Borders")
        toggles.prop(tool_settings, "uv_sculpt_all_islands", text="Sculpt All Islands")
        if tool.idname == 'sculpt.uv_sculpt_relax':
            props = tool.operator_properties("sculpt.uv_sculpt_relax")
            _labelled_prop(col, props, "relax_method", "Method")

        layout.separator(factor=0.5)

        # Falloff (collapsible)
        falloff_box = layout.box()
        if draw_collapsible_header(falloff_box, uv_ui, "expand_tool_falloff", "Falloff"):
            falloff_col = falloff_box.column()
            falloff_col.prop(uv_sculpt, "curve_distance_falloff_preset", expand=True)
            if uv_sculpt.curve_distance_falloff_preset == 'CUSTOM':
                falloff_col.template_curve_mapping(uv_sculpt, "curve_distance_falloff")


classes = (
    MIXAR_UV_PT_tools,
)
