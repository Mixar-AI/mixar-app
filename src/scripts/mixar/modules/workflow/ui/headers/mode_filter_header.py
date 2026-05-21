# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Topbar workspace-tab filter for the dual-mode UI system.

Monkey-patches TOPBAR_HT_upper_bar.draw_left so that in Zen mode the
workspace tab strip is hidden entirely — leaving only the menus + a clean
topbar.

The mode flip itself lives in the top-level "Zen Mode"/"Engine Mode" menu
that's appended to TOPBAR_MT_editor_menus (see mode_menu.py), so it sits
alongside File / Edit / Render / Window / Help with the same styling.

Note: install_topbar_filter() is intentionally called from
bootstrap/workflow_module.py during the synchronous bootstrap phase, before
the first UI paint. If installed during deferred UI loading instead, the
topbar would draw once with the unpatched method (showing all tabs) before
the patch lands — visible flicker on launch when the previous session ended
in Engine mode. There is no register()/classes contract here on purpose: the
bootstrap UI auto-loader checks for those and would otherwise call
register() a second time.
"""

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.workflow.constants import BASIC_WORKSPACE_NAME

_logger = get_logger(__name__)

_original_draw_left = None


def _patched_draw_left(self, context):
    """Replacement for TOPBAR_HT_upper_bar.draw_left.

    In Zen mode the workspace tab strip is omitted entirely. In Engine mode
    we use the native template_ID_tabs — the dedicated Zen Mode workspace
    is filtered out at the C++ level (see Mixar's overlay of
    interface_template_id.cc::template_ID_tabs) so it doesn't surface as a
    tab while preserving the native tab styling.
    """
    layout = self.layout
    window = context.window
    screen = context.screen

    bpy.types.TOPBAR_MT_editor_menus.draw_collapsible(context, layout)
    layout.separator(type='LINE')

    if screen.show_fullscreen:
        layout.operator(
            "screen.back_to_previous", icon='SCREEN_BACK', text="Back to Previous"
        )
        return

    workspace = getattr(context, "workspace", None)
    if workspace is not None and workspace.name == BASIC_WORKSPACE_NAME:
        # Zen mode: no workspace tab strip. The mode toggle lives in the
        # menu bar via mode_menu._draw_mode_menu_entry, so nothing else to
        # draw here.
        return

    layout.template_ID_tabs(
        window, "workspace",
        new="workspace.add",
        menu="TOPBAR_MT_workspace_menu",
    )


def install_topbar_filter():
    """Install the topbar tab-strip filter monkey patch. Idempotent."""
    global _original_draw_left
    cls = getattr(bpy.types, "TOPBAR_HT_upper_bar", None)
    if cls is None:
        _logger.warning("TOPBAR_HT_upper_bar not found; skipping mode filter")
        return

    if _original_draw_left is None:
        _original_draw_left = cls.draw_left

    cls.draw_left = _patched_draw_left


def uninstall_topbar_filter():
    """Restore the original topbar draw_left method. Idempotent."""
    global _original_draw_left
    cls = getattr(bpy.types, "TOPBAR_HT_upper_bar", None)
    if cls is None:
        return
    if _original_draw_left is not None:
        cls.draw_left = _original_draw_left
        _original_draw_left = None


classes = ()
