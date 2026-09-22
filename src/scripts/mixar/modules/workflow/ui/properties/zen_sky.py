# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Persistent world references for the reversible Zen sky toggle."""

import bpy
from bpy.props import PointerProperty


class MixarZenSkySettings(bpy.types.PropertyGroup):
    previous_world: PointerProperty(type=bpy.types.World)
    sky_world: PointerProperty(type=bpy.types.World)


classes = (MixarZenSkySettings,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mixar_zen_sky = PointerProperty(type=MixarZenSkySettings)


def unregister():
    del bpy.types.Scene.mixar_zen_sky
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
