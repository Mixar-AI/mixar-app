# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager state of the Connect engine sheet (`mixar.engine_connect`,
drawn by `ui/operators/engine_sheet_ui.py`).

The engine the sidebar has selected, new or existing project, the new
project's name and location, and the existing project's folder. The sheet's
rows, chips and fields write these (a pop-up's own operator properties
cannot be changed by another operator). Runtime-only: nothing here is
written into a .blend; the location the user picks is remembered in the
per-user config by `core/engine_projects.remember_location`.
"""

import bpy
from bpy.props import EnumProperty, StringProperty

ENGINE_ITEMS = [('GODOT', "Godot", ""), ('UNREAL', "Unreal Engine", "")]
MODE_ITEMS = [('NEW', "New project", "Make a new game project"),
              ('EXISTING', "Existing project", "Use a project you already have")]

_WM_ATTRS = (
    'mixar_engine_dialog_engine',
    'mixar_engine_dialog_mode',
    'mixar_engine_dialog_name',
    'mixar_engine_dialog_location',
    'mixar_engine_dialog_folder',
)


def _refresh_popups():
    try:
        from mixar.modules.common.utils.platform_utils import refresh_popup_dialogs
        refresh_popup_dialogs()
    except Exception:  # noqa: BLE001 - a stale sheet repaints on the next input anyway
        pass
    return None


def _repaint_sheet(_self, _context):
    """The folder browser (Browse) writes a field from its own window; the open
    sheet (a pop-up) would show the old value until the next input, so it is
    rebuilt once, from a timer (never inside the property write)."""
    try:
        if not bpy.app.timers.is_registered(_refresh_popups):
            bpy.app.timers.register(_refresh_popups, first_interval=0.0)
    except Exception:  # noqa: BLE001 - timers unavailable headless
        pass


def register():
    WM = bpy.types.WindowManager
    WM.mixar_engine_dialog_engine = EnumProperty(
        name="Engine", items=ENGINE_ITEMS, default='GODOT', options={'SKIP_SAVE'})
    WM.mixar_engine_dialog_mode = EnumProperty(
        name="Project", items=MODE_ITEMS, default='NEW', options={'SKIP_SAVE'})
    WM.mixar_engine_dialog_name = StringProperty(
        name="Project name", description="The new game's name; its folder is named after it",
        default="My Game", maxlen=60, options={'SKIP_SAVE'})
    WM.mixar_engine_dialog_location = StringProperty(
        name="Location", description="The folder the new project's folder is made in",
        default="", maxlen=1024, options={'SKIP_SAVE'},
        update=_repaint_sheet)
    WM.mixar_engine_dialog_folder = StringProperty(
        name="Project folder", description="The folder that holds your project",
        default="", maxlen=1024, options={'SKIP_SAVE'},
        update=_repaint_sheet)


def unregister():
    if bpy.app.timers.is_registered(_refresh_popups):
        bpy.app.timers.unregister(_refresh_popups)
    WM = bpy.types.WindowManager
    for attr in _WM_ATTRS:
        try:
            delattr(WM, attr)
        except AttributeError:
            pass
