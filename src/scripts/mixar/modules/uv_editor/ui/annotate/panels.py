# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Annotate Panel

Tool-based panel that surfaces the Annotate / Annotate Line / Annotate
Polygon / Annotate Eraser settings in the Mixar UV properties sidebar.
Mirrors the upstream Active Tool > Annotate N-panel content (annotation
color + layer, placement, stabilize stroke, radius, factor, line arrow
styles, eraser radius) in the Selection-style sub-section box layout
used by the rest of the Mixar UV panels.
"""

import bpy
from bpy.types import Panel

from .constants import ANNOTATION_LAYER_NAME_MAX, LABEL_FACTOR

_ANNOTATE_TOOLS = (
    'builtin.annotate',
    'builtin.annotate_line',
    'builtin.annotate_polygon',
    'builtin.annotate_eraser',
)


def _section(layout, title, icon='NONE'):
    """Open a Selection-style sub-section box."""
    box = layout.box()
    col = box.column(align=True)
    col.label(text=title, icon=icon)
    col.separator(factor=0.5)
    return col


def _row(col, label_text):
    """Open a `[label][control]` split row at the standard label factor."""
    split = col.split(factor=LABEL_FACTOR, align=True)
    split.label(text=label_text)
    return split


def _active_tool_from_image_editor(context):
    """Return the active workspace tool from an IMAGE_EDITOR area, or
    None.

    Panels in the CHANNELS region don't always receive the same tool
    context as the WINDOW region, so override the area before asking
    ToolSelectPanelHelper.
    """
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper

    # Prefer the panel's own area; fall back to the first IMAGE_EDITOR.
    area = context.area
    if area and area.type == 'IMAGE_EDITOR':
        with context.temp_override(area=area):
            return ToolSelectPanelHelper.tool_active_from_context(context)
    for a in context.screen.areas:
        if a.type == 'IMAGE_EDITOR':
            with context.temp_override(area=a):
                return ToolSelectPanelHelper.tool_active_from_context(context)
    return None


class MIXAR_UV_PT_annotate(Panel):
    """Annotate tool properties for the Mixar UV Properties space."""
    bl_label = "Annotate"
    bl_idname = "MIXAR_UV_PT_annotate"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'CHANNELS'
    bl_options = set()
    # Annotate always sits at the very top of the sidebar so the
    # annotation tool's settings (color, layer, stabilizer) stay
    # visible while drawing — even with a header tab also selected.
    # `bl_order=-10` keeps it above header panels (50) and the other
    # tool panels (Selection / UV Tool / Functions / Transform = 100).
    bl_order = -10

    @classmethod
    def poll(cls, context):
        sima = context.space_data
        if not (sima and sima.mode == 'MIXAR_UV'):
            return False
        # Tool-bar selection takes priority over header selection:
        # whenever an annotate tool is active, this panel shows
        # regardless of which header tab is selected.
        tool = _active_tool_from_image_editor(context)
        return tool is not None and tool.idname in _ANNOTATE_TOOLS

    @classmethod
    def msgbus_subscribe(cls, context, subscribe_to):
        """Refresh the panel when the active workspace tool changes."""
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

        tool = _active_tool_from_image_editor(context)
        if tool is None or tool.idname not in _ANNOTATE_TOOLS:
            return

        idname = tool.idname

        # ---- Tool selection buttons (no box wrapper, no header) ----
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
        _icon_handle = ToolSelectPanelHelper._icon_value_from_icon_handle

        annotate_tools = (
            ('builtin.annotate', "Annotate", "ops.gpencil.draw"),
            ('builtin.annotate_line', "Annotate Line",
             "ops.gpencil.draw.line"),
            ('builtin.annotate_polygon', "Annotate Polygon",
             "ops.gpencil.draw.poly"),
            ('builtin.annotate_eraser', "Annotate Eraser",
             "ops.gpencil.draw.eraser"),
        )

        tools_col = layout.column(align=True)
        for tool_id, label, icon_handle in annotate_tools:
            row = tools_col.row(align=True)
            row.scale_y = 1.5
            op = row.operator(
                "wm.tool_set_by_id",
                text=label,
                icon_value=_icon_handle(icon_handle),
                depress=(idname == tool_id),
            )
            op.name = tool_id

        layout.separator(factor=0.5)

        tool_settings = context.tool_settings
        col = _section(layout, "Annotate", icon='OUTLINER_OB_GREASEPENCIL')

        # ----- Annotation: color swatch + layer popover -----
        self._draw_annotation_row(col, context)

        # ----- Placement (not shown for the eraser — it doesn't draw
        # strokes, so the placement plane is meaningless). -----
        if idname != 'builtin.annotate_eraser':
            _row(col, "Placement").prop(
                tool_settings, "annotation_stroke_placement_view2d", text="")

        # ----- Tool-specific controls -----
        if idname == 'builtin.annotate':
            self._draw_scribble(col, tool)
        elif idname == 'builtin.annotate_line':
            self._draw_line(col, tool)
        elif idname == 'builtin.annotate_eraser':
            self._draw_eraser(col, context)
        # `builtin.annotate_polygon` has no extra settings.

    # ---------- Annotation color + layer popover ----------

    @staticmethod
    def _draw_annotation_row(col, context):
        gpd = context.annotation_data
        gpl = context.active_annotation_layer

        if gpd is None or gpl is None:
            # No annotation data yet — drawing into the viewport will
            # create it. Surface a hint rather than an empty row.
            _row(col, "Annotation").label(text="(none — draw to create)")
            return

        text = ""
        active_note = gpd.layers.active_note
        if active_note:
            text = active_note
            maxw = ANNOTATION_LAYER_NAME_MAX
            if len(text) > maxw:
                text = text[: maxw - 3] + "..."

        # Color swatch + popover share a nested split (factor 0.3 gives
        # the swatch a fixed slice and lets the popover button fill the
        # rest), with align=True so the two widgets share a single
        # rounded border instead of leaving a gap between them — the
        # gap was making the popover open into space that overlapped
        # the Placement row below it.
        ann_split = _row(col, "Annotation").split(factor=0.3, align=True)
        ann_split.prop(gpl, "color", text="")
        ann_split.popover(panel="TOPBAR_PT_annotation_layers", text=text)

    # ---------- Scribble (Annotate) controls ----------

    @staticmethod
    def _draw_scribble(col, tool):
        props = tool.operator_properties("gpencil.annotate")

        col.prop(props, "use_stabilizer", text="Stabilize Stroke")

        sub = col.column(align=True)
        sub.active = props.use_stabilizer

        _row(sub, "Radius").prop(
            props, "stabilizer_radius", text="", slider=True)
        _row(sub, "Factor").prop(
            props, "stabilizer_factor", text="", slider=True)

    # ---------- Line (Annotate Line) controls ----------

    @staticmethod
    def _draw_line(col, tool):
        props = tool.operator_properties("gpencil.annotate")
        _row(col, "Style Start").prop(props, "arrowstyle_start", text="")
        _row(col, "End").prop(props, "arrowstyle_end", text="")

    # ---------- Eraser controls ----------

    @staticmethod
    def _draw_eraser(col, context):
        prefs = context.preferences
        _row(col, "Radius").prop(
            prefs.edit, "grease_pencil_eraser_radius", text="")


classes = (
    MIXAR_UV_PT_annotate,
)
