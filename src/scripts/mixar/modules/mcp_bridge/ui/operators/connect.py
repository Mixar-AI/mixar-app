# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""One-time external AI client setup; account tokens stay in the desktop."""

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator

from mixar.config.config import add_config
from mixar.modules.common.i18n import iface_
from ...constants import SETUP_CHOICES
from ...core import runtime
from ...core.setup import connection_config


class MIXAR_OT_mcp_setup(Operator):
    bl_idname = "mixar.connect_ai"
    bl_label = "Connect Claude / Codex"
    bl_description = "Connect external AI assistants to your Mixar scenes with MCP"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=430)

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
        layout.separator()
        layout.label(text="Copy setup to enable MCP, then add it to your AI app:")
        for client, label in SETUP_CHOICES:
            layout.operator("mixar.copy_mcp_setup", text=iface_(label)).client = client


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


class MIXAR_OT_copy_mcp_setup(Operator):
    bl_idname = "mixar.copy_mcp_setup"
    bl_label = "Copy MCP Setup"
    bl_description = "Copy the connection setup without exposing account credentials"
    client: EnumProperty(items=(
        ('CLAUDE_CODE', "Claude Code", "Terminal setup command"),
        ('CLAUDE_DESKTOP', "Claude Desktop", "MCP server configuration"),
        ('CODEX', "Codex", "MCP server configuration")), default='CODEX')

    def execute(self, context):
        if not add_config("mcp_enabled", True):
            self.report({'WARNING'}, "MCP is enabled for this session; saving the preference failed")
        runtime.refresh()
        context.window_manager.clipboard = connection_config(
            self.client, bpy.utils.resource_path('LOCAL'), bpy.app.binary_path)
        self.report({'INFO'}, "MCP setup copied")
        return {'FINISHED'}


classes = (MIXAR_OT_mcp_setup, MIXAR_OT_set_mcp_enabled, MIXAR_OT_copy_mcp_setup)
