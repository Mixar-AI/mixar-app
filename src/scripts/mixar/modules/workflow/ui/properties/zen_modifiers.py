# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""UI list selection follows Blender's active modifier without storing a copy."""
import bpy
from bpy.props import BoolProperty, IntProperty


def _get_index(obj):
    active = obj.modifiers.active
    return obj.modifiers.find(active.name) if active else -1


def _set_index(obj, index):
    if 0 <= index < len(obj.modifiers) and obj.is_editable:
        obj.modifiers.active = obj.modifiers[index]
        popup = bpy.context.region_popup
        if popup and popup.type == 'TEMPORARY':
            popup.tag_refresh_ui()


def register():
    bpy.types.SpaceView3D.mixar_zen_controls_initialized = BoolProperty(options={'SKIP_SAVE'})
    bpy.types.Object.mixar_zen_modifier_index = IntProperty(
        name="Active Modifier", get=_get_index, set=_set_index,
        options={"SKIP_SAVE"},
    )


def unregister():
    del bpy.types.SpaceView3D.mixar_zen_controls_initialized
    del bpy.types.Object.mixar_zen_modifier_index
