# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import PropertyGroup


class MIXAR_ConnectorSettings(PropertyGroup):
    enabled: BoolProperty(
        name="Hub Sidecar",
        description="Expose this Mixar session to mixar-connector over loopback HTTP",
        default=True,
    )
    sidecar_port: IntProperty(
        name="Sidecar Port",
        default=7733,
        min=1024,
        max=65535,
    )
    hub_url: StringProperty(
        name="Hub URL",
        default="http://127.0.0.1:7734",
    )
    export_format: EnumProperty(
        name="Unreal Format",
        items=(
            ("usd", "USD", "Preferred interchange format for Unreal 5.8"),
            ("fbx", "FBX", "Unreal-axis FBX with embedded textures"),
            ("glb", "GLB", "glTF binary fallback"),
        ),
        default="usd",
    )
    last_export_path: StringProperty(name="Last Export", default="")


classes = (MIXAR_ConnectorSettings,)


def register():
    bpy.utils.register_class(MIXAR_ConnectorSettings)
    bpy.types.WindowManager.mixar_connector = bpy.props.PointerProperty(type=MIXAR_ConnectorSettings)


def unregister():
    if hasattr(bpy.types.WindowManager, "mixar_connector"):
        del bpy.types.WindowManager.mixar_connector
    bpy.utils.unregister_class(MIXAR_ConnectorSettings)
