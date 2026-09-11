# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""3D viewport header & tool-panel filter for the dual-mode UI system.

Monkey-patches:
- VIEW3D_HT_header.draw         → Mixar Solid/Rendered pills in Zen Mode
                                   AND on the Texturing / Texture Paint
                                   workspaces, so those surfaces match
                                   Zen / Cinema chrome instead of the
                                   stock Blender editor strip.
- VIEW3D_HT_tool_header.draw    → renders nothing in Zen mode (empty strip).
- VIEW3D_PT_tools_active.draw   → only Move / Rotate / Scale in Zen mode,
                                   as one vertically centred group.

The left T-panel used to be left alone: an even earlier build emptied it
completely and losing tool access made Zen Mode useless for anything beyond
viewing. The design resolves that tension instead of re-emptying it — Zen
keeps exactly the three transform tools (the design's centre-left strip), so
the canvas stays calm AND the viewport stays usable. Modes that have no
transform tools at all (sculpt / paint, where the toolbar IS the brush list)
fall through to the stock toolbar rather than rendering an empty strip.

We patch the contents instead of hiding the regions because hiding regions
gives Blender's collapsed-region arrow that lets the user expand them again
— that defeats the "calm canvas" goal of Zen mode.

Mode check uses context.workspace.name, not the global ui_mode preference.
This is workspace-driven so the right rendering happens regardless of which
window is active or whether a workspace switch is mid-flight, and so the
"AI Mode" workspace tab in Engine mode renders as a regular Pro workspace
(the Zen-only tool strip does NOT apply there). The Mixar viewport header
pills also apply on the Texturing / Texture Paint workspace tabs.
"""

import bpy

from mixar.config.logging_config import get_logger

from ...constants import (
    BASIC_WORKSPACE_NAME,
    TEXTURING_WORKSPACE_NAMES,
    ZEN_TRANSFORM_TOOL_IDS,
)
from ..operators import zen_tool_toggle

_logger = get_logger(__name__)

_original_header_draw = None
_original_tool_header_draw = None
_original_tools_active_draw = None

# Button height as a multiple of the widget unit. The design's strip is
# 138 px tall for three buttons at 1x (46 px each) and the widget unit is
# 20 px there, so 2.3 reproduces it. Blender's stock toolbar uses 1.75.
_ZEN_TOOL_SCALE_Y = 2.3

_DEFAULT_FALLBACK_TOOL = "builtin.select"
"""Safety net for `VIEW3D_PT_tools_active.tool_fallback_id`, which is
`"builtin.select"` (Tweak, the stock first tool). Only used if the panel has
not been registered yet — the attribute is read live when it is."""


def _is_basic_workspace(context) -> bool:
    """True if the viewport's workspace is the Zen Mode workspace."""
    ws = getattr(context, "workspace", None)
    return ws is not None and ws.name == BASIC_WORKSPACE_NAME


def _is_texturing_workspace(context) -> bool:
    """True if this window is on Mixar's texture-painting workspace."""
    ws = getattr(context, "workspace", None)
    return ws is not None and ws.name in TEXTURING_WORKSPACE_NAMES


def _uses_mixar_viewport_header(context) -> bool:
    """Zen and Texturing share the Mixar Solid/Rendered header pills.

    The tool-header empty-strip and the Move/Rotate/Scale toolbar stay
    Zen-only: Texturing still needs stock paint/brush chrome in those
    regions. Cinema Mode keeps its own C++ overlays and does not pass
    through here.
    """
    return _is_basic_workspace(context) or _is_texturing_workspace(context)


_SHADING_PILL_UNITS = 6.5
"""Shading pill width in UI units — the design's ~130 px at 1x."""


def _patched_header_draw(self, context):
    """Replacement for VIEW3D_HT_header.draw.

    Zen and Texturing: the viewport-type chooser + two shading pills
    (Solid / Rendered), styled natively per the design.
    Other Engine workspaces: defer to the original draw.
    """
    if not _uses_mixar_viewport_header(context):
        if _original_header_draw is not None:
            _original_header_draw(self, context)
        return

    layout = self.layout
    view = context.space_data
    if view is None or not hasattr(view, "shading"):
        return
    shading = view.shading

    # Tiny editor-type chooser (the icon at the very left of the header).
    # Texturing's custom spaces are omitted from that menu; View3D stays.
    layout.row(align=True).template_header()

    layout.separator_spacer()

    # Two shading pills — Solid and Rendered — per the design (UI.svg): the
    # live one at full opacity, the other at 49%. The stock four-way strip
    # (wireframe / solid / material / rendered) and the shading popover are
    # deliberately gone: Zen and Texturing offer the two modes people actually
    # switch between while making something, and the rest stays reachable from
    # Engine mode's other workspace tabs.
    row = layout.row(align=True)
    for value, label in (('SOLID', "Solid"), ('RENDERED', "Rendered")):
        cell = row.row(align=True)
        cell.ui_units_x = _SHADING_PILL_UNITS
        # `wm.context_set_enum`, NOT `prop_enum`: an enum-item button keeps
        # the value it applies in `hardmax`, which is the very field the
        # Mixar style tag writes its payload into — tagging one silently
        # rewrote the shading value it set (the viewport ended up with an
        # out-of-range enum that read back as ""). Operator buttons carry no
        # RNA data, so the tag is inert on them.
        props = cell.operator("wm.context_set_enum", text=label)
        props.data_path = "space_data.shading.type"
        props.value = value
        if hasattr(cell, "mixar_topbar_element"):
            cell.mixar_topbar_element(
                kind='VIEWPORT_PILL', active=(shading.type == value)
            )


def _patched_tool_header_draw(self, context):
    """Replacement for VIEW3D_HT_tool_header.draw.

    Zen mode: render nothing (the tool header strip stays as an empty bar but
    has no controls).
    Engine mode: defer to the original draw.
    """
    if not _is_basic_workspace(context):
        if _original_tool_header_draw is not None:
            _original_tool_header_draw(self, context)
        return
    # Zen mode: deliberately empty.


def _tool_helper():
    """Blender's ToolSelectPanelHelper, or None if bl_ui is unavailable.

    Imported lazily: the module is part of Blender's own startup scripts, so
    it is always present in practice, but a missing import must degrade to
    the stock toolbar rather than raising inside a draw callback.
    """
    try:
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
    except Exception:  # noqa: BLE001 — never raise from a draw callback
        return None
    return ToolSelectPanelHelper


def _active_tool_idname(helper, context):
    """idname of the viewport's active tool, or None when unreadable.

    `tool_active_from_context` dereferences `context.space_data` internally,
    hence the guard — this runs inside a draw callback, which must never
    raise.
    """
    if helper is None:
        return None
    try:
        return getattr(helper.tool_active_from_context(context), "idname", None)
    except Exception:  # noqa: BLE001 — never raise from a draw callback
        return None


def _fallback_tool_idname():
    """The viewport toolbar's own fallback tool idname.

    Read off the registered panel so a change to
    ``VIEW3D_PT_tools_active.tool_fallback_id`` is picked up rather than
    duplicated here.
    """
    panel = getattr(bpy.types, "VIEW3D_PT_tools_active", None)
    return getattr(panel, "tool_fallback_id", None) or _DEFAULT_FALLBACK_TOOL


def _tool_resolves(panel_cls, context):
    """Predicate: does an idname still resolve to a tool in this context?

    Used to reject a remembered tool that no longer exists in the current
    mode (a brush idname after leaving paint mode): activating it would
    return ``{'CANCELLED'}`` and leave the strip's exit looking dead.
    """

    def _resolves(idname):
        try:
            item, _index = panel_cls._tool_get_by_id(context, idname)
        except Exception:  # noqa: BLE001 — never raise from a draw callback
            return False
        return item is not None

    return _resolves


def _zen_tool_top_gap(context, tool_count: int) -> float:
    """Separator factor that vertically centres `tool_count` buttons.

    Panels are content-sized, so `separator_spacer()` — which only
    distributes leftover space, and only in horizontal layouts — cannot
    centre anything here. The gap is measured instead, mirroring the two
    formulas it depends on:

    * `U.widget_unit = round(18 * scale_factor) + 2 * pixelsize`
      (`wm_window.cc`), exposed as `system.ui_scale` / `system.pixel_size`.
    * `uiLayout::separator(factor)` spends `int(6 * UI_SCALE_FAC * factor)`
      px in a column (`interface_layout.cc`).

    Approximate to within the panel's own top padding, which is a few px.
    """
    region = getattr(context, "region", None)
    if region is None:
        return 0.0

    system = context.preferences.system
    ui_scale = getattr(system, "ui_scale", 1.0) or 1.0
    pixel_size = getattr(system, "pixel_size", 1.0) or 1.0

    widget_unit = round(18.0 * ui_scale) + 2.0 * pixel_size
    group_height = tool_count * widget_unit * _ZEN_TOOL_SCALE_Y
    gap_px = (region.height - group_height) * 0.5
    if gap_px <= 0.0:
        return 0.0
    return gap_px / (6.0 * ui_scale)


def _patched_tools_active_draw(self, context):
    """Replacement for VIEW3D_PT_tools_active.draw.

    Zen mode: Move / Rotate / Scale only, as one vertically centred group.
    Engine mode: defer to the original draw.

    The buttons stay stock ``wm.tool_set_by_id`` buttons — same tool ids, same
    icons off the real ToolDefs, same operator — because that is the only way
    Blender draws them as toolbar tools: ``but_is_tool`` matches the button's
    operator against ``WM_OT_tool_set_by_id`` by pointer, and that one test
    picks the toolbar widget style, the toolbar icon size, the icon
    desaturation and Mixar's toolbar SVG scaling. What makes the strip behave
    like three toggles is the ``name`` each button carries: a click on the
    already-active one is handed the tool to step back to instead of its own
    (see `zen_tool_toggle`).
    """
    helper = _tool_helper()
    cls = type(self)
    active_idname = _active_tool_idname(helper, context)
    # Where the strip's "off" should return to. Noted on every draw, in every
    # workspace, so a tool picked in Engine Mode (or from a keymap) is already
    # the way out by the time Zen Mode comes up.
    zen_tool_toggle.note_active_tool(active_idname)

    if not _is_basic_workspace(context):
        if _original_tools_active_draw is not None:
            _original_tools_active_draw(self, context)
        return

    items = []
    if helper is not None:
        for idname in ZEN_TRANSFORM_TOOL_IDS:
            try:
                item, _index = cls._tool_get_by_id(context, idname)
            except Exception:  # noqa: BLE001 — never raise from a draw callback
                item = None
            if item is not None:
                items.append((idname, item))

    if not items:
        # Modes whose toolbar IS the tool set (sculpt / paint brushes) have
        # no transform tools; an empty strip there would strand the user.
        if _original_tools_active_draw is not None:
            _original_tools_active_draw(self, context)
        return

    layout = self.layout
    gap = _zen_tool_top_gap(context, len(items))
    if gap > 0.0:
        layout.separator(factor=gap)

    col = layout.column(align=True)
    col.scale_y = _ZEN_TOOL_SCALE_Y
    fallback_idname = _fallback_tool_idname()
    resolves = _tool_resolves(cls, context)
    for idname, item in items:
        col.operator(
            "wm.tool_set_by_id",
            text="",
            depress=(idname == active_idname),
            icon_value=helper._icon_value_from_icon_handle(item.icon),
        ).name = zen_tool_toggle.toggle_target(
            idname, active_idname, fallback_idname, resolves
        )


def install_view3d_header_filter():
    """Install the viewport header, tool-header & toolbar filters. Idempotent."""
    global _original_header_draw, _original_tool_header_draw
    global _original_tools_active_draw

    header_cls = getattr(bpy.types, "VIEW3D_HT_header", None)
    if header_cls is None:
        _logger.warning("VIEW3D_HT_header not found; skipping header filter")
    else:
        if _original_header_draw is None:
            _original_header_draw = header_cls.draw
        header_cls.draw = _patched_header_draw

    tool_header_cls = getattr(bpy.types, "VIEW3D_HT_tool_header", None)
    if tool_header_cls is None:
        _logger.warning("VIEW3D_HT_tool_header not found; skipping tool header filter")
    else:
        if _original_tool_header_draw is None:
            _original_tool_header_draw = tool_header_cls.draw
        tool_header_cls.draw = _patched_tool_header_draw

    tools_cls = getattr(bpy.types, "VIEW3D_PT_tools_active", None)
    if tools_cls is None:
        _logger.warning("VIEW3D_PT_tools_active not found; skipping toolbar filter")
    else:
        # `draw` is inherited from ToolSelectPanelHelper; assigning here
        # shadows it on the VIEW_3D subclass only, so the image / node /
        # sequencer toolbars keep the stock draw.
        if _original_tools_active_draw is None:
            _original_tools_active_draw = tools_cls.draw
        tools_cls.draw = _patched_tools_active_draw


def uninstall_view3d_header_filter():
    """Restore the original viewport header, tool-header & toolbar draws.

    Idempotent.
    """
    global _original_header_draw, _original_tool_header_draw
    global _original_tools_active_draw

    header_cls = getattr(bpy.types, "VIEW3D_HT_header", None)
    if header_cls is not None and _original_header_draw is not None:
        header_cls.draw = _original_header_draw
        _original_header_draw = None

    tool_header_cls = getattr(bpy.types, "VIEW3D_HT_tool_header", None)
    if tool_header_cls is not None and _original_tool_header_draw is not None:
        tool_header_cls.draw = _original_tool_header_draw
        _original_tool_header_draw = None

    tools_cls = getattr(bpy.types, "VIEW3D_PT_tools_active", None)
    if tools_cls is not None and _original_tools_active_draw is not None:
        tools_cls.draw = _original_tools_active_draw
        _original_tools_active_draw = None


classes = ()
