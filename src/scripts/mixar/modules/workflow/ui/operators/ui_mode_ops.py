# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Window-level UI mode operators.

Two operators that flip Mixar between Zen mode (minimal viewport +
Agent Bubble + moodboard, no Engine workspace tabs) and Engine mode
(all workspaces, full Blender-style UI). The choice persists in
mixar.json so the next launch boots into the same mode.

The internal idents stay UI_MODE_AI / mixar.set_ui_mode_ai for backward
compatibility with persisted mixar.json values; the user-visible labels
have evolved from "AI Mode" → "Basic Mode" → "Zen Mode" (and
correspondingly "Pro Mode" → "Engine Mode") without breaking saved
config files.
"""

import bpy
from bpy.types import Operator

from mixar.config.config import (
    UI_MODE_AI,
    UI_MODE_PRO,
    set_ui_mode,
)
from mixar.config.logging_config import get_logger

from ...constants import BASIC_WORKSPACE_NAME
from ...core.workspace_loader import apply_ui_mode, ensure_basic_workspace

_logger = get_logger(__name__)


def _redraw_topbar(context):
    """Force the topbar to redraw so the tab strip reflects the new mode."""
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == 'TOPBAR':
            area.tag_redraw()


def _force_workspace_rebuild(target):
    """Make sure switching to `target` triggers a screen rebuild.

    If the active window is already on `target`, Blender's RNA setter
    short-circuits and no rebuild happens — which means popups (notably
    the startup splash) stay open after the user clicks "Start with Zen
    Mode". Bouncing through another workspace and back forces the rebuild
    and dismisses the popup.
    """
    window = bpy.context.window
    if window is None or target is None:
        return
    if window.workspace != target:
        window.workspace = target
        return
    other = next(
        (w for w in bpy.data.workspaces if w != target),
        None,
    )
    if other is None:
        return
    window.workspace = other
    window.workspace = target


class MIXAR_OT_set_ui_mode_ai(Operator):
    """Switch Mixar into Zen Mode (minimal viewport + Agent Bubble + moodboard)"""

    bl_idname = "mixar.set_ui_mode_ai"
    bl_label = "Zen Mode"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        set_ui_mode(UI_MODE_AI)
        # Materialize the dedicated Zen Mode workspace if this is the
        # user's first switch (or they previously deleted it). Independent
        # from the legacy "AI Mode" tab, so deleting that tab in Engine
        # mode doesn't break Zen Mode.
        ensure_basic_workspace()
        target = bpy.data.workspaces.get(BASIC_WORKSPACE_NAME)
        if target is None:
            self.report(
                {"WARNING"},
                "Could not create Zen Mode workspace — no template available",
            )
            return {"CANCELLED"}
        _force_workspace_rebuild(target)
        _redraw_topbar(context)
        _logger.info("Switched to Zen mode")
        return {"FINISHED"}


class MIXAR_OT_set_ui_mode_pro(Operator):
    """Switch Mixar into Engine Mode (full Blender-style workspaces)"""

    bl_idname = "mixar.set_ui_mode_pro"
    bl_label = "Engine Mode"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        set_ui_mode(UI_MODE_PRO)
        if not apply_ui_mode(UI_MODE_PRO):
            self.report({"WARNING"}, "Modeling workspace not found")
        _redraw_topbar(context)
        _logger.info("Switched to Engine mode")
        return {"FINISHED"}


classes = (
    MIXAR_OT_set_ui_mode_ai,
    MIXAR_OT_set_ui_mode_pro,
)
