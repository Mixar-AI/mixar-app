# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""One-time external AI client setup; account tokens stay in the desktop.

`mixar.connect_ai` opens the Connect MCP sheet (drawn by
`connect_sheet_ui` / `connect_sheet_plans`, state in `core/connect_state.py`);
the other operators here are its actions and keep their bl_idnames and
properties (agent, QA and profile-card contracts).
"""

import os
import subprocess
import sys

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator

from mixar.config.config import add_config
from mixar.modules.common.i18n import rpt_
from ...constants import OTHER_APP, PRODUCT_NAMES
from ...core import app_add, app_configs, connect_state, runtime
from ...core.setup import connection_config, launch
from . import connect_sheet_ui

APP_ITEMS = [(key, name, "") for key, name, _how in app_configs.APPS]


def _signed_in(context):
    """MCP acts for the signed-in account: no setup without one."""
    wm = context.window_manager
    return bool(getattr(wm, "mixie_chat_is_logged_in", False)) and not getattr(wm, "mixie_chat_session_expired", False)


def _refuse_signed_out(op, context):
    if _signed_in(context):
        return False
    op.report({'ERROR'}, "Sign in to Mixar before connecting AI apps")
    return True


def _save_tools_now():
    """Save the tool list right away (on a worker thread) so the AI app being
    set up gets every tool at its first connection."""
    from ...core import tool_snapshot
    tool_snapshot.forget()
    runtime.refresh()


def _enable(op):
    if not add_config("mcp_enabled", True):
        op.report({'WARNING'}, "MCP is enabled for this session; saving the preference failed")
    _save_tools_now()


def _ready(context):
    """AI apps can use Mixar only with a session (a guest's counts) and the agent
    server connected; the local relay alone refuses every scene call."""
    return _signed_in(context) and runtime.is_running() and bool(runtime.snapshot().get("connected"))


class MIXAR_OT_mcp_setup(Operator):
    bl_idname = "mixar.connect_ai"
    bl_label = "Connect MCP"
    bl_description = "Connect Claude, Codex, Cursor or another MCP app to your Mixar scenes"
    app: EnumProperty(name="App", items=APP_ITEMS, default='CLAUDE_CODE', translation_context=PRODUCT_NAMES)

    def invoke(self, context, event):
        """Open the sheet (`connect_sheet_ui`): centred in the main window with
        the island hidden, on the app passed in ``app`` (else the last one
        shown), IDLE unless an add it started is still running. Single
        instance: a second invoke while it is open does nothing."""
        if connect_state.dialog_open():
            return {'CANCELLED'}
        wm = context.window_manager
        if self.properties.is_property_set("app"):
            _select(wm, self.app)
        connect_state.reset(wm, adding=app_add.running())
        connect_state.set_dialog_open(True)
        try:
            modal = getattr(wm, "mixar_invoke_modal_dialog", None)
            if modal is None:
                return wm.invoke_props_dialog(self, width=connect_sheet_ui.SHEET_WIDTH)
            try:  # the sheet: no title row, framed card behind
                return modal(self, width=connect_sheet_ui.SHEET_WIDTH, sheet=True)
            except TypeError as exc:  # a binary predating `sheet`: plain dialog
                if "sheet" not in str(exc):
                    raise
                return modal(self, width=connect_sheet_ui.SHEET_WIDTH)
        except Exception:
            connect_state.set_dialog_open(False)
            raise

    def execute(self, context):
        connect_state.set_dialog_open(False)
        return {'FINISHED'}

    def cancel(self, context):
        connect_state.set_dialog_open(False)

    def draw(self, context):
        # Rendering lives in connect_sheet_ui / connect_sheet_plans (500-line rule).
        connect_sheet_ui.draw_dialog(self.layout, context.window_manager,
                                     _signed_in(context), _ready(context))


def _select(wm, app):
    """Show ``app``: a sidebar app, or a generic format under "Other app"."""
    if app in app_configs.FORMATS:
        wm.mixar_mcp_dialog_app = OTHER_APP
        wm.mixar_mcp_dialog_format = app
    else:
        wm.mixar_mcp_dialog_app = app


class MIXAR_OT_set_mcp_enabled(Operator):
    bl_idname = "mixar.set_mcp_enabled"
    bl_label = "Allow AI Apps to Use Mixar (MCP)"
    bl_description = ("Allow local AI apps (Claude, Codex, Cursor…) to use your Mixar account and scenes. "
                      "While this is off, connected AI apps report Mixar as not connected")
    enabled: BoolProperty(default=True)

    def execute(self, context):
        if self.enabled and _refuse_signed_out(self, context):
            return {'CANCELLED'}
        saved = add_config("mcp_enabled", self.enabled)
        if self.enabled:
            _save_tools_now()
        else:
            runtime.refresh()
        if not saved:
            self.report({'WARNING'}, "MCP preference applies until Mixar closes; saving failed")
        elif self.enabled and not runtime.is_running():
            self.report({'WARNING'}, "MCP is waiting for the desktop connection")
        elif self.enabled:
            self.report({'INFO'}, "MCP is on: AI apps can connect to Mixar")
        else:
            self.report({'INFO'}, "MCP is off: AI apps report Mixar as not connected until you turn it on")
        return {'FINISHED'}


class MIXAR_OT_set_mcp_ui_control(Operator):
    bl_idname = "mixar.set_mcp_ui_control"
    bl_label = "Let AI Apps Control Mixar's Interface"
    bl_description = ("Let connected AI apps see Mixar's interface and click, type and drag in it. "
                      "Your own mouse or keyboard always takes control back. Scene tools work either way")
    enabled: BoolProperty(default=True)

    def execute(self, context):
        saved = add_config("mcp_ui_control", self.enabled)
        runtime.refresh()
        if not saved:
            self.report({'WARNING'}, "This applies until Mixar closes; saving the preference failed")
        elif self.enabled:
            self.report({'INFO'}, "AI apps can now control Mixar's interface")
        else:
            self.report({'INFO'}, "AI apps can no longer control Mixar's interface")
        return {'FINISHED'}


class MIXAR_OT_copy_mcp_setup(Operator):
    bl_idname = "mixar.copy_mcp_setup"
    bl_label = "Copy MCP Setup"
    bl_description = ("Enable MCP and copy this app's setup. "
                      "It contains the launcher path, never account credentials")
    client: EnumProperty(items=APP_ITEMS, default='JSON', translation_context=PRODUCT_NAMES)

    def execute(self, context):
        if _refuse_signed_out(self, context):
            return {'CANCELLED'}
        _enable(self)
        context.window_manager.clipboard = connection_config(
            self.client, bpy.utils.resource_path('LOCAL'), bpy.app.binary_path)
        self.report({'INFO'}, "MCP setup copied. Paste it into your AI app where the dialog says")
        return {'FINISHED'}


class MIXAR_OT_mcp_add_to_app(Operator):
    bl_idname = "mixar.mcp_add_to_app"
    bl_label = "Add Mixar to App"
    bl_description = ("Enable MCP and add Mixar to this app's MCP servers: Claude Code through its "
                      "claude mcp command, Codex in its config.toml (the previous file is kept as a backup)")
    app: EnumProperty(items=[item for item in APP_ITEMS if item[0] in app_configs.ADDABLE],
                      translation_context=PRODUCT_NAMES)

    def execute(self, context):
        if _refuse_signed_out(self, context):
            return {'CANCELLED'}
        _enable(self)
        command, args = launch(bpy.utils.resource_path('LOCAL'), bpy.app.binary_path, True)
        if not app_add.start(self.app, command, args):
            self.report({'INFO'}, "Already adding Mixar to this app")
            return {'CANCELLED'}
        # The sheet shows the busy pill until `app_add._announce` lands the
        # outcome (ADDED recap / ERROR); a closed sheet gets a toast instead.
        connect_state.begin_add(context.window_manager, self.app)
        self.report({'INFO'}, rpt_("Adding Mixar to {app}…").format(app=app_configs.label(self.app)))
        return {'FINISHED'}


class MIXAR_OT_mcp_open_app_config(Operator):
    bl_idname = "mixar.mcp_open_app_config"
    bl_label = "Open MCP Config File"
    bl_description = "Open this app's MCP configuration file (or its folder when the file does not exist yet)"
    app: EnumProperty(items=APP_ITEMS, translation_context=PRODUCT_NAMES)

    def execute(self, context):
        path = app_configs.config_path(self.app)
        target = path if path is not None and path.is_file() else path.parent if path is not None else None
        if target is None or not target.exists():
            self.report({'WARNING'}, "This app's settings folder was not found. Is the app installed?")
            return {'CANCELLED'}
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-t", str(target)] if target.is_file() else ["open", str(target)])
            elif sys.platform == "win32":
                if target.is_file():
                    subprocess.Popen(["notepad.exe", str(target)])
                else:
                    os.startfile(str(target))  # noqa: S606 - a folder the user asked to open
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError:
            self.report({'WARNING'}, "Could not open the file; copy the setup instead")
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (MIXAR_OT_mcp_setup, MIXAR_OT_set_mcp_enabled, MIXAR_OT_set_mcp_ui_control, MIXAR_OT_copy_mcp_setup,
           MIXAR_OT_mcp_add_to_app, MIXAR_OT_mcp_open_app_config)
