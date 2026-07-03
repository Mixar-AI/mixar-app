# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image to 3D Properties

Scene properties for the Image to 3D panel - 3D model generation from images
using dynamically loaded models from the v2 API.
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    PointerProperty,
    StringProperty,
)


def _get_model_enum_items(self, context):
    """Dynamic callback for model enum items."""
    try:
        from mixar.bootstrap.model_3d_cache import get_model_enum_items

        return get_model_enum_items(self, context)
    except ImportError:
        return [
            ("ERROR", "Cache not available", "Model cache module not loaded", "ERROR", 0)
        ]


def register():
    """Register Image to 3D scene properties."""

    # Prompt for generation (optional, for context)
    bpy.types.Scene.mixie_image_to_3d_prompt = StringProperty(
        name="Prompt",
        description="Optional text prompt for context",
        maxlen=1024,
        default="",
    )

    # Input image selection
    bpy.types.Scene.mixie_image_to_3d_image = PointerProperty(
        name="Input Image",
        description="Input image for 3D model generation",
        type=bpy.types.Image,
    )

    # Use selected moodboard image
    bpy.types.Scene.mixie_image_to_3d_use_selected = BoolProperty(
        name="Use Selected Moodboard Image",
        description="Use the selected image from moodboard instead of file picker",
        default=True,
    )

    # Model selection - DYNAMIC ENUM
    bpy.types.Scene.mixie_image_to_3d_model = EnumProperty(
        name="Model",
        description="Select 3D generation model",
        items=_get_model_enum_items,
    )

    # Generation state flag (SKIP_SAVE so undo doesn't restore stale state)
    bpy.types.Scene.mixie_image_to_3d_is_generating = BoolProperty(
        name="Is Generating",
        description="Whether 3D model generation is in progress",
        default=False,
        options={'SKIP_SAVE'},
    )

    # Error message for display in UI
    bpy.types.Scene.mixie_image_to_3d_error = StringProperty(
        name="Error Message",
        description="Last error message from 3D generation",
        default="",
        options={'SKIP_SAVE'},
    )


def unregister():
    """Unregister Image to 3D scene properties."""
    props = [
        "mixie_image_to_3d_prompt",
        "mixie_image_to_3d_image",
        "mixie_image_to_3d_use_selected",
        "mixie_image_to_3d_model",
        "mixie_image_to_3d_is_generating",
        "mixie_image_to_3d_error",
    ]
    for prop in props:
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass
