# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from ..bake.utils.bake_info_properties import MBakeInfoProps


class MImageAtlasSegment(bpy.types.PropertyGroup):

    name: StringProperty(
        name="Name", description="Name of Image Atlas Segments", default=""
    )

    tile_x: IntProperty(default=0)
    tile_y: IntProperty(default=0)

    width: IntProperty(default=1024)
    height: IntProperty(default=1024)

    unused: BoolProperty(default=False)

    bake_info: PointerProperty(type=MBakeInfoProps)


class MImageAtlas(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", description="Name of Image Atlas", default="")

    is_image_atlas: BoolProperty(default=False)

    color: EnumProperty(
        name="Atlas Base Color",
        items=(
            ("WHITE", "White", ""),
            ("BLACK", "Black", ""),
            ("TRANSPARENT", "Transparent", ""),
        ),
        default="BLACK",
    )

    # float_buffer : BoolProperty(default=False)

    segments: CollectionProperty(type=MImageAtlasSegment)


classes = (
    MImageAtlasSegment,
    MImageAtlas,
)


def register():
    """Register image atlas properties.

    This function is idempotent - safe to call multiple times.
    """
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise

    # Register yia property on Image datablock
    if not hasattr(bpy.types.Image, 'yia'):
        bpy.types.Image.yia = PointerProperty(type=MImageAtlas)


def unregister():
    """Unregister image atlas properties"""
    # Unregister Image property
    if hasattr(bpy.types.Image, 'yia'):
        del bpy.types.Image.yia

    # Unregister classes
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
