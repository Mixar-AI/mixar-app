# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-channel source properties for Fill layers.

This module defines MChannelSource PropertyGroup for optional per-channel
image/solid overrides in Fill layers. This enables Substance Painter-style
multi-texture fills where different channels can use different images while
sharing projection settings.
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    StringProperty,
)


# Channel source type enum items
channel_source_type_items = (
    ("DEFAULT", "Use Layer", "Use the layer's main source"),
    ("IMAGE", "Image", "Use a specific image for this channel"),
    ("SOLID", "Solid", "Use a solid color or value"),
)

# Interpolation/filtering enum items
channel_interpolation_items = (
    ("Linear", "Linear", "Bilinear filtering (smooth)"),
    ("Closest", "Closest", "Nearest neighbor (pixelated)"),
    ("Cubic", "Cubic", "Bicubic filtering (smoothest)"),
)


def update_channel_source_type(self, context):
    """Update callback when channel source type changes.

    This callback is triggered when the user changes source_type for a channel.
    It should update the node graph to use the appropriate source.

    Args:
        self: The property being updated (MChannelSource).
        context: Blender context.
    """
    # Import here to avoid circular dependency
    from .channel_source_callbacks import on_channel_source_type_changed
    on_channel_source_type_changed(self, context)


def update_channel_source_image(self, context):
    """Update callback when channel source image changes.

    Args:
        self: The property being updated (MChannelSource).
        context: Blender context.
    """
    from .channel_source_callbacks import on_channel_source_image_changed
    on_channel_source_image_changed(self, context)


def update_channel_source_solid(self, context):
    """Update callback when channel solid color/value changes.

    Args:
        self: The property being updated (MChannelSource).
        context: Blender context.
    """
    from .channel_source_callbacks import on_channel_source_solid_changed
    on_channel_source_solid_changed(self, context)


class MChannelSource(bpy.types.PropertyGroup):
    """Optional per-channel source override for multi-texture fills.

    This allows Fill layers to have different images per channel while
    sharing projection and transform settings. Follows Substance Painter
    pattern where you can assign different texture maps to Color, Roughness,
    Normal, etc. channels.

    Attributes:
        source_type: Whether to use layer source, image, or solid color
        image_name: Name of the Blender image to use (when source_type='IMAGE')
        solid_color: RGB color value (for COLOR channels when source_type='SOLID')
        solid_value: Single float value (for VALUE channels when source_type='SOLID')
        interpolation: Texture filtering mode (Linear, Closest, Cubic)
        source_node: Name of the source node in the layer tree
        enabled: Whether this override is active
    """

    enabled: BoolProperty(
        name="Enable Override",
        description="Enable per-channel source override",
        default=False,
        update=update_channel_source_type,
    )

    source_type: EnumProperty(
        name="Source Type",
        description="Source type for this channel",
        items=channel_source_type_items,
        default="DEFAULT",
        update=update_channel_source_type,
    )

    image_name: StringProperty(
        name="Image",
        description="Image to use for this channel",
        default="",
        update=update_channel_source_image,
    )

    solid_color: FloatVectorProperty(
        name="Color",
        description="Solid color for this channel",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(0.5, 0.5, 0.5),
        update=update_channel_source_solid,
    )

    solid_value: FloatProperty(
        name="Value",
        description="Solid value for this channel (0-1)",
        subtype="FACTOR",
        min=0.0,
        max=1.0,
        default=0.5,
        update=update_channel_source_solid,
    )

    interpolation: EnumProperty(
        name="Filtering",
        description="Texture interpolation/filtering mode",
        items=channel_interpolation_items,
        default="Linear",
        update=update_channel_source_image,
    )

    # Node reference for the per-channel source node
    source_node: StringProperty(
        name="Source Node",
        description="Name of the source node in the layer tree",
        default="",
    )


classes = (MChannelSource,)


def register():
    """Register channel source property classes."""
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise


def unregister():
    """Unregister channel source property classes."""
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
