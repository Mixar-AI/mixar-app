# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image Gen Properties

Scene properties for the Image Gen panel - AI image generation
using dynamically loaded models and styles from the v2 API.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class MixieImageGenRefImage(bpy.types.PropertyGroup):
    """A single reference image for image generation"""

    image: PointerProperty(
        name="Image",
        description="Reference image",
        type=bpy.types.Image,
    )


def _get_model_enum_items(self, context):
    """Dynamic callback for model enum items."""
    try:
        from mixar.bootstrap.imagegen_cache import get_model_enum_items

        items = get_model_enum_items(self, context)
        if items:
            return items
    except Exception as e:
        logger.error("[ImageGen] Model enum callback error: %s", e)
    return [
        ("flash", "Flash", "Fast generation", "IMAGE_DATA", 0),
        ("pro", "Pro", "Higher quality generation", "IMAGE_DATA", 1),
    ]


def _get_style_enum_items(self, context):
    """Dynamic callback for style enum items."""
    try:
        from mixar.bootstrap.imagegen_cache import get_style_enum_items

        items = get_style_enum_items(self, context)
        if items:
            return items
    except Exception as e:
        logger.error("[ImageGen] Style enum callback error: %s", e)
    return [
        ("none", "None", "No specific style", "BRUSH_DATA", 0),
        ("photorealistic", "Photorealistic", "Photorealistic style", "BRUSH_DATA", 1),
        ("artistic", "Artistic", "Artistic painterly style", "BRUSH_DATA", 2),
        ("3d_render", "3D Render", "3D rendered look", "BRUSH_DATA", 3),
        ("concept_art", "Concept Art", "Concept art style", "BRUSH_DATA", 4),
        ("anime", "Anime", "Anime/manga style", "BRUSH_DATA", 5),
    ]


def _get_aspect_ratio_enum_items(self, context):
    """Dynamic callback for aspect ratio enum items."""
    try:
        from mixar.bootstrap.imagegen_cache import get_aspect_ratio_enum_items

        items = get_aspect_ratio_enum_items(self, context)
        if items:
            return items
    except Exception as e:
        logger.error("[ImageGen] Aspect ratio enum callback error: %s", e)
    return [
        ("1:1", "1:1", "Square", "FULLSCREEN_ENTER", 0),
        ("16:9", "16:9", "Widescreen", "FULLSCREEN_ENTER", 1),
        ("9:16", "9:16", "Portrait", "FULLSCREEN_ENTER", 2),
        ("4:3", "4:3", "Standard", "FULLSCREEN_ENTER", 3),
        ("3:4", "3:4", "Portrait Standard", "FULLSCREEN_ENTER", 4),
    ]


def _get_resolution_enum_items(self, context):
    """Dynamic callback for resolution enum items."""
    try:
        from mixar.bootstrap.imagegen_cache import get_resolution_enum_items

        items = get_resolution_enum_items(self, context)
        if items:
            return items
    except Exception as e:
        logger.error("[ImageGen] Resolution enum callback error: %s", e)
    return [("1K", "1K", "1024px (Standard)", "RENDER_RESULT", 0)]


def register():
    """Register Image Gen scene properties."""
    # Register PropertyGroup first
    bpy.utils.register_class(MixieImageGenRefImage)

    # Prompt for generation
    bpy.types.Scene.mixie_imagegen_prompt = StringProperty(
        name="Prompt",
        description="Text description of desired image",
        maxlen=1024,
        default="",
    )

    # Negative prompt - what to avoid
    bpy.types.Scene.mixie_imagegen_negative_prompt = StringProperty(
        name="Negative Prompt",
        description="What to avoid in generation",
        maxlen=1024,
        default="",
    )

    # Reference images collection
    bpy.types.Scene.mixie_imagegen_ref_images = CollectionProperty(
        name="Reference Images",
        description="Reference images for generation",
        type=MixieImageGenRefImage,
    )

    # Model selection - DYNAMIC ENUM
    bpy.types.Scene.mixie_imagegen_model = EnumProperty(
        name="Model",
        description="AI model for image generation",
        items=_get_model_enum_items,
    )

    # Style preset selection - DYNAMIC ENUM
    bpy.types.Scene.mixie_imagegen_style = EnumProperty(
        name="Style",
        description="Style preset for image generation",
        items=_get_style_enum_items,
    )

    # Aspect ratio selection - DYNAMIC ENUM
    bpy.types.Scene.mixie_imagegen_aspect_ratio = EnumProperty(
        name="Aspect Ratio",
        description="Aspect ratio for generated images",
        items=_get_aspect_ratio_enum_items,
    )

    # Resolution selection - DYNAMIC ENUM
    bpy.types.Scene.mixie_imagegen_resolution = EnumProperty(
        name="Resolution",
        description="Output resolution for generated images",
        items=_get_resolution_enum_items,
    )

    # Number of images to generate
    bpy.types.Scene.mixie_imagegen_num_images = IntProperty(
        name="Number of Images",
        description="Number of images to generate (1-4)",
        default=1,
        min=1,
        max=4,
    )

    # Generation state flag (SKIP_SAVE so undo doesn't restore stale state)
    bpy.types.Scene.mixie_imagegen_is_generating = BoolProperty(
        name="Is Generating",
        description="Whether image generation is in progress",
        default=False,
        options={'SKIP_SAVE'},
    )

    # Error message for display in UI
    bpy.types.Scene.mixie_imagegen_error = StringProperty(
        name="Error Message",
        description="Last error message from image generation",
        default="",
        options={'SKIP_SAVE'},
    )


def unregister():
    """Unregister Image Gen scene properties."""
    props = [
        "mixie_imagegen_prompt",
        "mixie_imagegen_negative_prompt",
        "mixie_imagegen_ref_images",
        "mixie_imagegen_model",
        "mixie_imagegen_style",
        "mixie_imagegen_aspect_ratio",
        "mixie_imagegen_resolution",
        "mixie_imagegen_num_images",
        "mixie_imagegen_is_generating",
        "mixie_imagegen_error",
    ]
    for prop in props:
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass

    # Unregister PropertyGroup
    try:
        bpy.utils.unregister_class(MixieImageGenRefImage)
    except RuntimeError:
        pass
