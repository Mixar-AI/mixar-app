# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""3D viewport header & tool-panel filter for the dual-mode UI system.

Monkey-patches:
- VIEW3D_HT_header.draw         → in Zen Mode only, a floating
                                   liquid-glass Wireframe / Solid /
                                   Material Preview / Rendered strip plus
                                   the shading popover and a guides chip
                                   (grid + relationship lines). Every other
                                   workspace — Texturing included — keeps
                                   Blender's full viewport header.
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
(the Zen-only tool strip does NOT apply there).

Texturing / Texture Paint are ordinary Engine workspaces here: their 3D
viewport keeps the stock header — Editor Type dropdown, View/Select/Add
menus, mode selector, the native shading strip and the rest — because a
texture-painting workspace is a working editor, not a calm canvas.
"""

import bpy

from mixar.config.logging_config import get_logger

from ...constants import BASIC_WORKSPACE_NAME, ZEN_TRANSFORM_TOOL_IDS
from ...core import viewport_guides
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


def _patched_header_draw(self, context):
    """Replacement for VIEW3D_HT_header.draw.

    Zen mode: a floating Move/Rotate/Scale-style liquid-glass strip of
    Wireframe / Solid / Material Preview / Rendered plus the guides chip
    and the shading options popover. The header region itself has no bar.
    Every other workspace — Texturing and Texture Paint included — defers
    to the original draw and keeps Blender's full viewport header.
    """
    if not _is_basic_workspace(context):
        if _original_header_draw is not None:
            _original_header_draw(self, context)
        return

    layout = self.layout
    view = context.space_data
    if view is None or not hasattr(view, "shading"):
        return
    shading = view.shading

    # No editor-type chooser and no full-width header chrome: the header
    # overlaps the viewport and clears transparent, so this cluster is a
    # floating group. Spacer parks it on the right.
    layout.separator_spacer()

    # Keep native RNA enum buttons: available modes depend on the render
    # engine (Workbench has no Material Preview). The Zen painter supplies
    # one glass pane without replacing RNA selection, tooltips or dispatch.
    # The popover stays outside the aligned group. Zen also parks a guides
    # chip beside that strip (same cluster wiring as the popover) so floor
    # grid + relationship lines flip as one view-state toggle. That chip is
    # a Zen surface with its own aligned row: one cell, so the shared glass
    # painter gives it a round chip of the strip's material, and `depress`
    # paints the same circular selected wash a chosen shading icon gets.
    # A toggle is not a shading mode, so it stays out of the enum capsule.
    cluster = layout.row(align=False)
    surface = cluster.mixar_surface(theme="ZEN")
    row = surface.row(align=True)
    row.prop(shading, "type", text="", expand=True)
    cluster.separator(factor=0.4)
    chip = cluster.mixar_surface(theme="ZEN").row(align=True)
    chip.operator(
        "mixar.zen_toggle_guides",
        text="",
        icon="GRID",
        depress=viewport_guides.guides_shown(view),
    )
    # Match the shading strip material with a separate icon-only popover chip.
    cluster.separator(factor=0.4)
    options = cluster.mixar_surface(theme="ZEN").row(align=True)
    options.popover(panel="VIEW3D_PT_shading", text="", icon="PREFERENCES")


def _patched_tool_header_draw(self, context):
    """Replacement for VIEW3D_HT_tool_header.draw.

    Zen mode: render nothing. The region overlaps and clears transparent,
    so an empty tool-header must not paint button-section chrome.
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

    surface = layout.mixar_surface(theme="ZEN")
    # align=True is load-bearing: it sets `alignnr` so C++ paints one glass
    # pane for the column instead of three separate pills.
    col = surface.column(align=True)
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
