# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""3D viewport header & tool-panel filter for the dual-mode UI system.

Monkey-patches:
- VIEW3D_HT_header.draw         → renders only the shading-mode buttons
                                   (wireframe/solid/material/rendered + popover)
                                   when the viewport is in the Zen Mode workspace.
- VIEW3D_HT_tool_header.draw    → renders nothing in Zen mode (empty strip).

The left T-panel (VIEW3D_PT_tools_active) is intentionally LEFT ALONE —
Zen Mode keeps the standard tool icons so users can still grab brush /
sculpt / select tools. Earlier builds emptied the T-panel as part of the
"calm canvas" look but losing tool access made Zen Mode useless for
anything beyond viewing.

We patch the contents instead of hiding the regions because hiding regions
gives Blender's collapsed-region arrow that lets the user expand them again
— that defeats the "calm canvas" goal of Zen mode.

Mode check uses context.workspace.name, not the global ui_mode preference.
This is workspace-driven so the right rendering happens regardless of which
window is active or whether a workspace switch is mid-flight, and so the
"AI Mode" workspace tab in Engine mode renders as a regular Pro workspace
(filter does NOT apply there — only the dedicated Zen Mode workspace).
"""

import bpy

from mixar.config.logging_config import get_logger

from ...constants import BASIC_WORKSPACE_NAME

_logger = get_logger(__name__)

_original_header_draw = None
_original_tool_header_draw = None


def _is_basic_workspace(context) -> bool:
    """True if the viewport's workspace is the Zen Mode workspace."""
    ws = getattr(context, "workspace", None)
    return ws is not None and ws.name == BASIC_WORKSPACE_NAME


def _patched_header_draw(self, context):
    """Replacement for VIEW3D_HT_header.draw.

    Zen mode: just the viewport-type chooser + shading mode buttons + popover.
    Engine mode: defer to the original draw.
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

    # Tiny editor-type chooser (the icon at the very left of the header).
    layout.row(align=True).template_header()

    layout.separator_spacer()

    # Shading mode buttons (wireframe / solid / material / rendered) + popover.
    row = layout.row(align=True)
    row.prop(shading, "type", text="", expand=True)
    sub = row.row(align=True)
    sub.popover(panel="VIEW3D_PT_shading", text="")


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


def install_view3d_header_filter():
    """Install the viewport header & tool-header filters. Idempotent.

    Note: VIEW3D_PT_tools_active is deliberately not patched — the
    standard tool icons are kept in Zen Mode so the user can still
    pick brushes / sculpt / select tools.
    """
    global _original_header_draw, _original_tool_header_draw

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


def uninstall_view3d_header_filter():
    """Restore the original viewport header & tool-header draws. Idempotent."""
    global _original_header_draw, _original_tool_header_draw

    header_cls = getattr(bpy.types, "VIEW3D_HT_header", None)
    if header_cls is not None and _original_header_draw is not None:
        header_cls.draw = _original_header_draw
        _original_header_draw = None

    tool_header_cls = getattr(bpy.types, "VIEW3D_HT_tool_header", None)
    if tool_header_cls is not None and _original_tool_header_draw is not None:
        tool_header_cls.draw = _original_tool_header_draw
        _original_tool_header_draw = None


classes = ()
