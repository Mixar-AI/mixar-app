# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export preset operators and menus for glTF, OBJ, and FBX formats.

Uses Blender's AddPresetBase machinery to provide:
- Built-in engine presets (Unity, Unreal, Godot) shipped via overlay
- User-saveable presets persisted to the Blender user config directory
"""

import bpy
from bl_operators.presets import AddPresetBase


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

_SKIP_PROPS = frozenset(('rna_type', 'name'))


def _preset_values_for(pg_type):
    """Return a list of 'varname.prop' strings for every user-facing property."""
    return [
        f"gs.{p.identifier}"
        for p in pg_type.bl_rna.properties
        if p.identifier not in _SKIP_PROPS
    ]


# ---------------------------------------------------------------------------
#  glTF
# ---------------------------------------------------------------------------

class MIXAR_OT_gltf_export_preset_add(AddPresetBase, bpy.types.Operator):
    bl_idname = "mixar.gltf_export_preset_add"
    bl_label = "Add glTF Export Preset"
    preset_menu = "MIXAR_MT_gltf_export_presets"
    preset_subdir = "mixar/gltf_export"
    preset_defines = ["gs = bpy.context.window_manager.mixar_export_gltf"]

    @property
    def preset_values(self):
        return _preset_values_for(bpy.types.MGltfExportSettings)


class MIXAR_MT_gltf_export_presets(bpy.types.Menu):
    bl_label = "glTF Export Presets"
    preset_subdir = "mixar/gltf_export"
    preset_operator = "script.execute_preset"
    draw = bpy.types.Menu.draw_preset


# ---------------------------------------------------------------------------
#  OBJ
# ---------------------------------------------------------------------------

class MIXAR_OT_obj_export_preset_add(AddPresetBase, bpy.types.Operator):
    bl_idname = "mixar.obj_export_preset_add"
    bl_label = "Add OBJ Export Preset"
    preset_menu = "MIXAR_MT_obj_export_presets"
    preset_subdir = "mixar/obj_export"
    preset_defines = ["gs = bpy.context.window_manager.mixar_export_obj"]

    @property
    def preset_values(self):
        return _preset_values_for(bpy.types.MObjExportSettings)


class MIXAR_MT_obj_export_presets(bpy.types.Menu):
    bl_label = "OBJ Export Presets"
    preset_subdir = "mixar/obj_export"
    preset_operator = "script.execute_preset"
    draw = bpy.types.Menu.draw_preset


# ---------------------------------------------------------------------------
#  FBX
# ---------------------------------------------------------------------------

class MIXAR_OT_fbx_export_preset_add(AddPresetBase, bpy.types.Operator):
    bl_idname = "mixar.fbx_export_preset_add"
    bl_label = "Add FBX Export Preset"
    preset_menu = "MIXAR_MT_fbx_export_presets"
    preset_subdir = "mixar/fbx_export"
    preset_defines = ["gs = bpy.context.window_manager.mixar_export_fbx"]

    @property
    def preset_values(self):
        return _preset_values_for(bpy.types.MFbxExportSettings)


class MIXAR_MT_fbx_export_presets(bpy.types.Menu):
    bl_label = "FBX Export Presets"
    preset_subdir = "mixar/fbx_export"
    preset_operator = "script.execute_preset"
    draw = bpy.types.Menu.draw_preset


# ---------------------------------------------------------------------------
#  Registration (auto-discovered by bootstrap via classes tuple)
# ---------------------------------------------------------------------------

classes = (
    MIXAR_OT_gltf_export_preset_add,
    MIXAR_MT_gltf_export_presets,
    MIXAR_OT_obj_export_preset_add,
    MIXAR_MT_obj_export_presets,
    MIXAR_OT_fbx_export_preset_add,
    MIXAR_MT_fbx_export_presets,
)
