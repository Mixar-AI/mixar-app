# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager state of the Export sheet (`mixar.export_menu`).

The picked format tile, the file name, the quality and each format's
settings. Runtime-only (``SKIP_SAVE`` on a WindowManager group): the choices
last for the session and nothing is written into a .blend.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty

from ...constants import (
    ENGINE_FORMAT_ITEMS,
    FORMAT_ITEMS,
    GLTF_ITEMS,
    IMAGE_FORMAT_ITEMS,
    QUALITY_ITEMS,
    VIDEO_FORMAT_ITEMS,
)


class MixarExportMenuProps(bpy.types.PropertyGroup):
    format: EnumProperty(  # type: ignore[valid-type]
        name="Format", items=FORMAT_ITEMS, default="GLB", options={'SKIP_SAVE'})
    file_name: StringProperty(  # type: ignore[valid-type]
        name="File Name", description="Name of the exported file, without its extension",
        default="", maxlen=72, options={'SKIP_SAVE'})
    quality: EnumProperty(  # type: ignore[valid-type]
        name="Quality", items=QUALITY_ITEMS, default="GOOD", options={'SKIP_SAVE'})
    gltf_variant: EnumProperty(  # type: ignore[valid-type]
        name="glTF File", items=GLTF_ITEMS, default="GLB", options={'SKIP_SAVE'})
    engine_format: EnumProperty(  # type: ignore[valid-type]
        name="Engine File", items=ENGINE_FORMAT_ITEMS, default="FBX", options={'SKIP_SAVE'})
    image_format: EnumProperty(  # type: ignore[valid-type]
        name="Image Format", items=IMAGE_FORMAT_ITEMS, default="PNG", options={'SKIP_SAVE'})
    video_format: EnumProperty(  # type: ignore[valid-type]
        name="Video Format", items=VIDEO_FORMAT_ITEMS, default="MP4", options={'SKIP_SAVE'})
    selected_only: BoolProperty(  # type: ignore[valid-type]
        name="Selected Objects Only", default=False, options={'SKIP_SAVE'})
    strip_chat: BoolProperty(  # type: ignore[valid-type]
        name="Leave Out the Agent Chat", default=True, options={'SKIP_SAVE'})
    include_animation: BoolProperty(  # type: ignore[valid-type]
        name="Include Animation", default=True, options={'SKIP_SAVE'})


classes = (MixarExportMenuProps,)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass  # already registered by a reload
    bpy.types.WindowManager.mixar_export_menu = PointerProperty(
        type=MixarExportMenuProps, options={'SKIP_SAVE'})


def unregister():
    try:
        del bpy.types.WindowManager.mixar_export_menu
    except AttributeError:
        pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
