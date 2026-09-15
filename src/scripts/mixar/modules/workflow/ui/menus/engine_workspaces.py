# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Overflow access for Engine tabs beside the centered mode switch."""
import bpy
from mixar.modules.workflow.constants import BASIC_WORKSPACE_NAME


class MIXAR_MT_engine_workspaces(bpy.types.Menu):
    bl_label = "Workspaces"
    bl_description = "Workspaces"

    def draw(self, context):
        for workspace in sorted(bpy.data.workspaces, key=lambda item: item.name.casefold()):
            if workspace.name in {BASIC_WORKSPACE_NAME, "Basic Mode", "AI Mode"}:
                continue
            op = self.layout.operator(
                "wm.context_set_id", text=workspace.name,
                icon='RADIOBUT_ON' if workspace == context.workspace else 'RADIOBUT_OFF',
            )
            op.data_path = "window.workspace"
            op.value = workspace.name
        self.layout.separator()
        self.layout.operator("workspace.duplicate", text="Duplicate Workspace", icon='DUPLICATE')
        self.layout.menu("TOPBAR_MT_workspace_menu", text="Workspace Options")


classes = (MIXAR_MT_engine_workspaces,)
