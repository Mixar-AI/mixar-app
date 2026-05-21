# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Asset export settings PropertyGroup.

Only contains the format tab selector. Per-format settings live in
their own PropertyGroups (gltf_export_settings, obj_export_settings,
fbx_export_settings) registered on the WindowManager.
"""

import bpy
from bpy.props import EnumProperty
from bpy.types import PropertyGroup


class MAssetExportSettings(PropertyGroup):
    """Shared asset export settings (format tab selector)."""

    tab: EnumProperty(
        name='Export Format',
        items=[
            ('GLTF', "glTF", "Export as glTF / GLB"),
            ('OBJ', "OBJ", "Export as Wavefront OBJ"),
            ('FBX', "FBX", "Export as Autodesk FBX"),
        ],
        default='GLTF',
    )


def register():
    bpy.utils.register_class(MAssetExportSettings)
    bpy.types.WindowManager.mixar_asset_export = bpy.props.PointerProperty(
        type=MAssetExportSettings,
    )


def unregister():
    if hasattr(bpy.types.WindowManager, 'mixar_asset_export'):
        del bpy.types.WindowManager.mixar_asset_export
    bpy.utils.unregister_class(MAssetExportSettings)
