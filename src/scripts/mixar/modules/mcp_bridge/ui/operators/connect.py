# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""One-time external AI client setup; account tokens stay in the desktop."""

import os
import subprocess
import sys
import textwrap

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator

from mixar.config.config import add_config
from mixar.modules.common.i18n import iface_, rpt_
from ...constants import SETUP_GUIDE_URL
from ...core import app_add, app_configs, runtime
from ...core.setup import connection_config, launch, render, stable_launch

#: App names are product names: a context with no catalog entries keeps
#: "Cursor" from being shown as a translated word.
PRODUCT_NAMES = "Mixar product name"
APP_ITEMS = [(key, name, "") for key, name, _how in app_configs.APPS]
SNIPPET_COLUMNS = 72


def _enable(op):
    if not add_config("mcp_enabled", True):
        op.report({'WARNING'}, "MCP is enabled for this session; saving the preference failed")
    runtime.refresh()


def _snippet_lines(text):
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip())
        yield from textwrap.wrap(line, SNIPPET_COLUMNS, subsequent_indent=" " * (indent + 4),
                                 break_long_words=True, break_on_hyphens=False) or [""]


class MIXAR_OT_mcp_setup(Operator):
    bl_idname = "mixar.connect_ai"
    bl_label = "Connect AI Apps (MCP)"
    bl_description = "Connect Claude, Codex, Cursor or another MCP app to your Mixar scenes"
    app: EnumProperty(name="App", items=APP_ITEMS, default='CLAUDE_CODE', translation_context=PRODUCT_NAMES)

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Let your AI assistant use Mixar scenes and controls.")
        layout.label(text="UI control is free; scene tools and generation use credits.")
        layout.label(text="Sign in once. Your AI app can start Mixar when needed.")
        row = layout.row()
        if runtime.enabled():
            row.label(text="MCP enabled", icon='CHECKMARK')
            row.operator("mixar.set_mcp_enabled", text="Disable").enabled = False
        else:
            row.operator("mixar.set_mcp_enabled", text="Enable MCP").enabled = True
        on = runtime.ui_control_enabled()
        row = layout.row()
        row.alignment = 'LEFT'
        row.enabled = runtime.enabled()
        row.operator("mixar.set_mcp_ui_control", text="Let AI apps control Mixar's interface",
                     icon='CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT', emboss=False).enabled = not on
        layout.separator()
        layout.prop(self, "app")
        how = next(how for key, _name, how in app_configs.APPS if key == self.app)
        layout.label(text=iface_(how), translate=False)
        box = layout.box().column(align=True)
        for line in _snippet_lines(render(self.app, *stable_launch())):
            box.label(text=line, translate=False)
        row = layout.row()
        name = app_configs.label(self.app)
        if self.app in app_configs.ADDABLE:
            # Never drawn as busy: a popup redraws only on input, so a "busy"
            # button outlived the add and swallowed the next click. The operator
            # refuses a duplicate while one runs, and a toast reports the result.
            row.operator("mixar.mcp_add_to_app", text=iface_("Add to {app}").format(app=name),
                         translate=False, icon='ADD').app = self.app
        row.operator("mixar.copy_mcp_setup", text="Copy", icon='COPYDOWN').client = self.app
        if app_configs.config_path(self.app) is not None:
            row.operator("mixar.mcp_open_app_config", text="Open Config File", icon='FILE_FOLDER').app = self.app
        layout.label(text="Then restart the app's MCP connection.")
        layout.separator()
        row = layout.row()
        row.operator("mixar.copy_mcp_setup", text="Copy MCP Config", icon='COPYDOWN').client = 'JSON'
        row.operator("wm.url_open", text="Setup Guide", icon='HELP').url = SETUP_GUIDE_URL


class MIXAR_OT_set_mcp_enabled(Operator):
    bl_idname = "mixar.set_mcp_enabled"
    bl_label = "Enable MCP"
    bl_description = "Allow local AI clients to use your Mixar account and scenes"
    enabled: BoolProperty(default=True)

    def execute(self, context):
        saved = add_config("mcp_enabled", self.enabled)
        runtime.refresh()
        if not saved:
            self.report({'WARNING'}, "MCP preference applies until Mixar closes; saving failed")
        elif self.enabled and not runtime.is_running():
            self.report({'WARNING'}, "MCP is waiting for the desktop connection")
        elif self.enabled:
            self.report({'INFO'}, "MCP enabled")
        else:
            self.report({'INFO'}, "MCP disabled")
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
        _enable(self)
        context.window_manager.clipboard = connection_config(
            self.client, bpy.utils.resource_path('LOCAL'), bpy.app.binary_path)
        self.report({'INFO'}, "MCP setup copied. Paste it into your AI app; Setup Guide shows where")
        return {'FINISHED'}


class MIXAR_OT_mcp_add_to_app(Operator):
    bl_idname = "mixar.mcp_add_to_app"
    bl_label = "Add Mixar to App"
    bl_description = ("Enable MCP and add Mixar to this app's MCP servers: Claude Code through its "
                      "claude mcp command, Codex in its config.toml (the previous file is kept as a backup)")
    app: EnumProperty(items=[item for item in APP_ITEMS if item[0] in app_configs.ADDABLE],
                      translation_context=PRODUCT_NAMES)

    def execute(self, context):
        _enable(self)
        command, args = launch(bpy.utils.resource_path('LOCAL'), bpy.app.binary_path, True)
        if not app_add.start(self.app, command, args):
            self.report({'INFO'}, "Already adding Mixar to this app")
            return {'CANCELLED'}
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
