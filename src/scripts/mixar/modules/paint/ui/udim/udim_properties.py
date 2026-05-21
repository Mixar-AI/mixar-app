# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from ..bake.utils.bake_info_properties import MBakeInfoProps


class MUDIMAtlasSegmentTile(bpy.types.PropertyGroup):
    name: StringProperty(default="1001")
    number: IntProperty(default=1001, min=1001, max=2000)


class MUDIMAtlasSegment(bpy.types.PropertyGroup):

    name: StringProperty(
        name="Name", description="Name of UDIM Atlas Segments", default=""
    )

    unused: BoolProperty(default=False)

    bake_info: PointerProperty(type=MBakeInfoProps)
    base_color: FloatVectorProperty(
        subtype="COLOR", size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.0, 0.0)
    )

    base_tiles: CollectionProperty(type=MUDIMAtlasSegmentTile)


class MUDIMAtlas(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", description="Name of UDIM Atlas", default="")

    is_udim_atlas: BoolProperty(default=False)

    segments: CollectionProperty(type=MUDIMAtlasSegment)


class MUDIMInfo(bpy.types.PropertyGroup):
    base_color: FloatVectorProperty(
        subtype="COLOR", size=4, min=0.0, max=1.0, default=(0.0, 0.0, 0.0, 0.0)
    )


classes = (
    MUDIMAtlasSegmentTile,
    MUDIMAtlasSegment,
    MUDIMAtlas,
    MUDIMInfo,
)


def register():
    """Register UDIM properties.

    This function is idempotent - safe to call multiple times.
    """
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise

    # Register yua property on Image datablock
    if not hasattr(bpy.types.Image, 'yua'):
        bpy.types.Image.yua = PointerProperty(type=MUDIMAtlas)
    if not hasattr(bpy.types.Image, 'yui'):
        bpy.types.Image.yui = PointerProperty(type=MUDIMInfo)


def unregister():
    """Unregister UDIM properties"""
    # Unregister Image properties
    if hasattr(bpy.types.Image, 'yua'):
        del bpy.types.Image.yua
    if hasattr(bpy.types.Image, 'yui'):
        del bpy.types.Image.yui

    # Unregister classes
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
