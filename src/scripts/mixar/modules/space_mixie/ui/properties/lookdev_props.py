# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev Properties

Property definitions for the Lookdev mode - generating images from depth maps.
"""

import bpy
from bpy.props import (
    PointerProperty,
    BoolProperty,
    StringProperty,
)


def register():
    """Register Lookdev scene properties"""
    # Depth map image selection
    bpy.types.Scene.mixie_lookdev_depth_image = PointerProperty(
        type=bpy.types.Image,
        name="Depth Map",
        description="Depth map image for lookdev generation"
    )

    # Toggle for using selected moodboard image vs file picker
    bpy.types.Scene.mixie_lookdev_use_selected = BoolProperty(
        name="Use Selected Image",
        description="Use selected moodboard image as depth map instead of file picker",
        default=True
    )

    # Prompt for generation
    bpy.types.Scene.mixie_lookdev_prompt = StringProperty(
        name="Prompt",
        description="Positive prompt for image generation",
        maxlen=1024,
        default=""
    )

    # Generation state (SKIP_SAVE so undo doesn't restore stale state)
    bpy.types.Scene.mixie_lookdev_is_generating = BoolProperty(
        name="Is Generating",
        description="Whether lookdev generation is in progress",
        default=False,
        options={'SKIP_SAVE'},
    )

    # Error message for display in UI
    bpy.types.Scene.mixie_lookdev_error = StringProperty(
        name="Error Message",
        description="Last error message from Lookdev generation",
        default="",
        options={'SKIP_SAVE'},
    )


def unregister():
    """Unregister Lookdev scene properties"""
    props = [
        "mixie_lookdev_is_generating",
        "mixie_lookdev_prompt",
        "mixie_lookdev_use_selected",
        "mixie_lookdev_depth_image",
        "mixie_lookdev_error",
    ]
    for prop in props:
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass
