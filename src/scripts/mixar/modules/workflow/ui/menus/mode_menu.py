# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Top-level mode toggle rendered alongside File / Edit / Render / Window /
Help in the topbar menu list.

Renders the inactive mode's switch operator with PULLDOWN_MENU emboss so
it picks up the same flat, hover-highlighted styling as the native menu
labels — but a single click runs the operator and flips the mode (no
dropdown, no second click).

install_mode_menu_hook() runs synchronously from workflow_module.py so the
entry is in place before the first paint.
"""

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.workflow.constants import BASIC_WORKSPACE_NAME

_logger = get_logger(__name__)

_appended = False


def _draw_mode_menu_entry(self, context):
    """Append the mode toggle to TOPBAR_MT_editor_menus.

    Drawn on its own row with NORMAL emboss so the button renders as a
    boxed, embossed widget (rounded rect + subtle fill) that stands out
    from the flat File / Edit / Render / Window / Help labels. A single
    click runs the operator directly and flips the mode. The dedicated
    row keeps the emboss override local so it can't leak onto anything
    else appended to the menu after us.
    """
    row = self.layout.row()
    row.emboss = 'NORMAL'
    workspace = getattr(context, "workspace", None)
    if workspace is not None and workspace.name == BASIC_WORKSPACE_NAME:
        row.operator("mixar.set_ui_mode_pro", text="Engine Mode")
    else:
        row.operator("mixar.set_ui_mode_ai", text="Zen Mode")


def install_mode_menu_hook():
    """Append the mode toggle to the editor-menus draw. Idempotent."""
    global _appended
    if _appended:
        return
    parent = getattr(bpy.types, "TOPBAR_MT_editor_menus", None)
    if parent is None:
        _logger.warning("TOPBAR_MT_editor_menus not found; skipping mode menu hook")
        return
    parent.append(_draw_mode_menu_entry)
    _appended = True


def uninstall_mode_menu_hook():
    """Remove the appended draw. Idempotent."""
    global _appended
    if not _appended:
        return
    parent = getattr(bpy.types, "TOPBAR_MT_editor_menus", None)
    if parent is not None:
        try:
            parent.remove(_draw_mode_menu_entry)
        except ValueError:
            pass
    _appended = False


classes = ()
