# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Overflow access for Engine tabs beside the centered mode switch."""
import bpy
from mixar.modules.workflow.constants import BASIC_WORKSPACE_NAME

_INTERNAL_WORKSPACES = {BASIC_WORKSPACE_NAME, "Basic Mode", "AI Mode"}

OVERFLOW_CONTEXT_PREFIX = "mixar_overflow_workspace_"
"""Native topbar layout (`interface_mixar_topbar_tabs.cc`) sets one context
pointer per hidden tab on the overflow dropdown: `<prefix>0`, `<prefix>1`, …"""


def _workspace_item(layout, context, workspace):
    op = layout.operator(
        "wm.context_set_id", text=workspace.name,
        icon='RADIOBUT_ON' if workspace == context.workspace else 'RADIOBUT_OFF',
    )
    op.data_path = "window.workspace"
    op.value = workspace.name


def overflow_workspaces(context):
    """Workspaces whose tabs the topbar hid, in tab order."""
    hidden = []
    while True:
        workspace = getattr(context, f"{OVERFLOW_CONTEXT_PREFIX}{len(hidden)}", None)
        if workspace is None:
            return hidden
        hidden.append(workspace)


class MIXAR_MT_engine_workspaces(bpy.types.Menu):
    bl_label = "Workspaces"
    bl_description = "Workspaces"

    def draw(self, context):
        for workspace in sorted(bpy.data.workspaces, key=lambda item: item.name.casefold()):
            if workspace.name in _INTERNAL_WORKSPACES:
                continue
            _workspace_item(self.layout, context, workspace)
        self.layout.separator()
        self.layout.operator("workspace.duplicate", text="Duplicate Workspace", icon='DUPLICATE')
        self.layout.menu("TOPBAR_MT_workspace_menu", text="Workspace Options")


class MIXAR_MT_workspace_overflow(bpy.types.Menu):
    """Workspace tabs that did not fit before the Zen/Engine switch.

    Drawn after the tab strip; native layout shows it (after the "+") only
    while some tabs are hidden. It also offers New Workspace, so it is a
    complete workspace switcher on its own.
    """

    bl_label = "More Workspaces"
    bl_description = "Workspaces that do not fit in the tab strip"

    def draw(self, context):
        hidden = overflow_workspaces(context)
        if not hidden:
            # Opened without the native context (e.g. after a popup refresh):
            # every workspace is still one click away.
            hidden = [workspace for workspace in bpy.data.workspaces
                      if workspace.name not in _INTERNAL_WORKSPACES]
        for workspace in hidden:
            _workspace_item(self.layout, context, workspace)
        self.layout.separator()
        self.layout.operator("workspace.add", text="New Workspace", icon='ADD')


classes = (MIXAR_MT_engine_workspaces, MIXAR_MT_workspace_overflow)
