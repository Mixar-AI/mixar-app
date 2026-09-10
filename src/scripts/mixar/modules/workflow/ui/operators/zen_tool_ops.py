# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Toggle behaviour for the Zen Mode Move / Rotate / Scale strip.

The stock toolbar buttons PERSIST: ``wm.tool_set_by_id`` activates a tool
and Blender never has "no tool" — exactly one tool is always active for the
workspace. Zen's strip is only three buttons, so a click on the one that is
already active has to land somewhere else, and the answer is "back where
you came from": the tool that was active before the strip was used (Select
Box, Tweak, a brush, whatever it was), falling back to the toolbar's own
``tool_fallback_id`` when there is nothing to restore — a transform tool
reached from a keymap, a fresh viewport, a file that was just opened.

Only NON-transform tools are remembered, so Move → Rotate → click Rotate
returns to the user's select tool instead of ping-ponging between the two
transform tools. Every click that lands on the active button therefore has
the same, predictable way out of the strip.

The remembered tool is one slot for the whole Zen session rather than one
per area: Blender stores the active tool on the WORKSPACE (the writable
``WorkSpaceTool.idname``), not per viewport, so two viewports in Zen Mode
share a single tool anyway and a per-area cache would model something that
is not per-area.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...constants import ZEN_TRANSFORM_TOOL_IDS

_logger = get_logger(__name__)

#: Safety net for `VIEW3D_PT_tools_active.tool_fallback_id`, which is
#: "builtin.select" (Tweak, the stock first tool). Only used if the panel
#: has not been registered yet — the attribute is read live when it is.
_DEFAULT_FALLBACK_TOOL = "builtin.select"

#: The last non-transform tool the strip displaced, or None.
_previous_tool_idname = None


def _tool_helper():
    """Blender's ToolSelectPanelHelper, or None if bl_ui is unavailable.

    Imported lazily, exactly as the toolbar filter does it: the module is
    part of Blender's own startup scripts and is always present in practice
    but a missing import must degrade rather than raise out of a click.
    """
    try:
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
    except Exception:  # noqa: BLE001 — degrade, never raise
        return None
    return ToolSelectPanelHelper


def _active_tool_idname(context):
    """idname of the viewport's active tool, or None when unreadable."""
    helper = _tool_helper()
    if helper is None:
        return None
    try:
        # Dereferences context.space_data internally.
        tool = helper.tool_active_from_context(context)
    except Exception:  # noqa: BLE001 — degrade, never raise
        return None
    return getattr(tool, "idname", None)


def _fallback_tool_idname():
    """The viewport toolbar's own fallback tool idname.

    Read off the registered panel so a change to
    ``VIEW3D_PT_tools_active.tool_fallback_id`` is picked up rather than
    duplicated here.
    """
    panel = getattr(bpy.types, "VIEW3D_PT_tools_active", None)
    return getattr(panel, "tool_fallback_id", None) or _DEFAULT_FALLBACK_TOOL


def _tool_to_activate(clicked_idname, active_idname, previous_idname, fallback_idname):
    """Which tool a click on ``clicked_idname`` must activate.

    Pure, so the decide-then-set contract can be pinned without a live
    Blender; the operator below is only the plumbing around it.
    """
    if clicked_idname != active_idname:
        return clicked_idname
    if previous_idname and previous_idname not in ZEN_TRANSFORM_TOOL_IDS:
        return previous_idname
    return fallback_idname


def _tool_to_remember(active_idname):
    """The tool to file away as "previous", or None to keep what we have.

    Only a non-transform tool is worth remembering: activating Move while
    Rotate is active must not overwrite the select tool the user actually
    came from.
    """
    if active_idname and active_idname not in ZEN_TRANSFORM_TOOL_IDS:
        return active_idname
    return None


def _set_active_tool(idname) -> bool:
    """Activate ``idname``; False when Blender refused it.

    A menu tool that no longer exists in the current mode (a brush idname
    remembered from a paint mode) is an ordinary miss, not an error: the
    caller falls back rather than breaking the click.
    """
    try:
        result = bpy.ops.wm.tool_set_by_id(name=idname)
    except Exception:  # noqa: BLE001 — a stale id must not break the click
        _logger.debug("zen tool: cannot activate %r", idname, exc_info=True)
        return False
    return result != {'CANCELLED'}


class MIXAR_OT_toggle_zen_transform_tool(Operator):
    """Activate a Zen transform tool, or step off the active one."""

    bl_idname = "mixar.toggle_zen_transform_tool"
    bl_label = "Transform Tool"
    bl_description = (
        "Activate this tool, or turn it off and restore the tool that was "
        "active before it"
    )
    bl_options = {"REGISTER", "INTERNAL"}

    tool_idname: bpy.props.StringProperty(
        name="Tool",
        description="Tool idname this button toggles",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        global _previous_tool_idname

        active_idname = _active_tool_idname(context)
        fallback_idname = _fallback_tool_idname()
        target_idname = _tool_to_activate(
            self.tool_idname, active_idname, _previous_tool_idname, fallback_idname
        )

        if not _set_active_tool(target_idname):
            # The remembered tool is useless here (its mode is gone), so try
            # the panel's fallback before giving up on the click.
            if target_idname != fallback_idname and _set_active_tool(fallback_idname):
                target_idname = fallback_idname
            else:
                self.report({'WARNING'}, "Cannot activate tool")
                return {'CANCELLED'}

        remembered = _tool_to_remember(active_idname)
        if remembered is not None:
            _previous_tool_idname = remembered
        return {'FINISHED'}


classes = (MIXAR_OT_toggle_zen_transform_tool,)
