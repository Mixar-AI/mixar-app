# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import Panel

from mixar.modules.connector.core.sidecar import sidecar_port


class MIXAR_PT_connector_panel(Panel):
    bl_label = "Unreal Connector"
    bl_idname = "MIXAR_PT_connector_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mixar"

    def draw(self, context):
        layout = self.layout
        settings = getattr(context.window_manager, "mixar_connector", None)
        if settings is None:
            layout.label(text="Connector properties not registered")
            return
        layout.prop(settings, "enabled")
        layout.prop(settings, "sidecar_port")
        layout.prop(settings, "hub_url")
        layout.prop(settings, "export_format")
        layout.operator("mixar.connector_start_sidecar", icon="PLAY")
        layout.operator("mixar.connector_export_unreal", icon="EXPORT")
        layout.label(text=f"Sidecar :{sidecar_port()}")
        layout.label(text="Hub :7734 · Unreal MCP :8000/mcp · UnrealMCP TCP :55557")
        if settings.last_export_path:
            layout.label(text=settings.last_export_path)


classes = (MIXAR_PT_connector_panel,)
