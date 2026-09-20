# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import Operator

from mixar.modules.connector.core.sidecar import sidecar_port, start_sidecar
from mixar.modules.connector.core.unreal_export import export_scene_for_unreal


class MIXAR_OT_connector_start_sidecar(Operator):
    bl_idname = "mixar.connector_start_sidecar"
    bl_label = "Start Connector Sidecar"
    bl_description = "Expose Mixar to the hub over loopback HTTP"

    def execute(self, context):
        settings = context.window_manager.mixar_connector
        port = start_sidecar(settings.sidecar_port)
        self.report({"INFO"}, f"Connector sidecar on 127.0.0.1:{port}")
        return {"FINISHED"}


class MIXAR_OT_connector_export_unreal(Operator):
    bl_idname = "mixar.connector_export_unreal"
    bl_label = "Export Scene to Unreal"
    bl_description = "Export the current Mixar scene as Unreal-ready USD/FBX/GLB"

    def execute(self, context):
        settings = context.window_manager.mixar_connector
        try:
            result = export_scene_for_unreal(settings.export_format)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.last_export_path = result["filepath"]
        self.report({"INFO"}, f"Exported {result['filename']} ({result['mesh_count']} meshes)")
        return {"FINISHED"}


classes = (
    MIXAR_OT_connector_start_sidecar,
    MIXAR_OT_connector_export_unreal,
)
