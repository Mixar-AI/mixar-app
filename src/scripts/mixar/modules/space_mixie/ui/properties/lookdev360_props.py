# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev 360 Properties

Scene properties for the Lookdev 360 panel including prompt, style image,
generation state, and material checkpoint for undo functionality.
"""

import bpy
from bpy.props import (
    BoolProperty,
    PointerProperty,
    StringProperty,
)


def register():
    """Register lookdev 360 scene properties."""
    # Prompt for generation
    bpy.types.Scene.mixie_lookdev360_prompt = StringProperty(
        name="Prompt",
        description="Positive prompt for texture generation",
        default="",
    )

    # Style image selection mode
    bpy.types.Scene.mixie_lookdev360_use_selected_image = BoolProperty(
        name="Use Selected Moodboard Image",
        description="Use the selected image from the moodboard as style reference",
        default=True,
    )

    # Style image from file picker
    bpy.types.Scene.mixie_lookdev360_style_image = PointerProperty(
        name="Style Image",
        description="Style reference image for texture generation",
        type=bpy.types.Image,
    )

    # Generation state flag (SKIP_SAVE so undo doesn't restore stale state)
    bpy.types.Scene.mixie_lookdev360_is_generating = BoolProperty(
        name="Is Generating",
        description="Whether texture generation is in progress",
        default=False,
        options={'SKIP_SAVE'},
    )

    # Material checkpoint for undo (JSON string)
    bpy.types.Scene.mixie_lookdev360_checkpoint = StringProperty(
        name="Material Checkpoint",
        description="JSON checkpoint of original materials for undo",
        default="",
    )

    # Flag to show restore button
    bpy.types.Scene.mixie_lookdev360_has_applied = BoolProperty(
        name="Has Applied Materials",
        description="Whether generated materials have been applied",
        default=False,
    )

    # Error message for display in UI
    bpy.types.Scene.mixie_lookdev360_error = StringProperty(
        name="Error Message",
        description="Last error message from Lookdev 360 generation",
        default="",
        options={'SKIP_SAVE'},
    )


def unregister():
    """Unregister lookdev 360 scene properties."""
    props = [
        "mixie_lookdev360_prompt",
        "mixie_lookdev360_use_selected_image",
        "mixie_lookdev360_style_image",
        "mixie_lookdev360_is_generating",
        "mixie_lookdev360_checkpoint",
        "mixie_lookdev360_has_applied",
        "mixie_lookdev360_error",
    ]
    for prop in props:
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass
