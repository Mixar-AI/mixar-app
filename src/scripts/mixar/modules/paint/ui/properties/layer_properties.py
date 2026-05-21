# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer property groups for Mixar layers system.

This module contains the main layer property groups:
- MixarLayerMask: Individual layer mask properties
- MixarLayer: Main layer properties with channels and masks collections

Channel properties are defined in layer_channel_properties.py.
Update callbacks are defined in layer_properties_callbacks.py.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)

from .layer_properties_callbacks import (
    update_layer_visible,
    update_layer_opacity,
    update_layer_blend_mode,
)
from .layer_channel_properties import MixarLayerChannel


class MixarLayerMask(bpy.types.PropertyGroup):
    """Property group for individual layer mask"""

    # ========== IDENTITY ==========
    name: StringProperty(name="Mask Name", default="Mask")

    # ========== BASIC SETTINGS ==========
    enable: BoolProperty(
        name="Enable", default=True, description="Enable/disable this mask"
    )

    active_edit: BoolProperty(
        name="Active Edit", default=False, description="Set as active for editing"
    )

    # ========== BLENDING ==========
    blend_type: EnumProperty(
        name="Blend Type",
        items=[
            ("MIX", "Mix", "Mix"),
            ("MULTIPLY", "Multiply", "Multiply"),
            ("DARKEN", "Darken", "Darken"),
            ("LIGHTEN", "Lighten", "Lighten"),
        ],
        default="MIX",
        description="Mask blend type",
    )

    intensity_value: FloatProperty(
        name="Mask Opacity",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        precision=3,
        description="Mask opacity/intensity",
    )

    # ========== MASK TYPE & SOURCE ==========
    type: EnumProperty(
        name="Mask Type",
        items=[
            ("IMAGE", "Image", "Image texture mask"),
            ("VCOL", "Vertex Color", "Vertex color mask"),
            ("HEMI", "Fake Lighting", "Hemisphere/fake lighting mask"),
            ("OBJECT_INDEX", "Object Index", "Object index mask"),
            ("EDGE_DETECT", "Edge Detect", "Edge detection mask"),
            ("AO", "Ambient Occlusion", "Ambient occlusion mask"),
            ("COLOR_ID", "Color ID", "Color ID mask"),
            ("BACKFACE", "Backface", "Backface mask"),
            ("MODIFIER", "Modifier", "Modifier mask"),
        ],
        default="IMAGE",
        description="Mask type",
    )

    source_input: EnumProperty(
        name="Source Input",
        items=[
            ("RGB", "RGB", "Use RGB channels"),
            ("ALPHA", "Alpha", "Use alpha channel"),
            ("R", "Red", "Use red channel only"),
            ("G", "Green", "Use green channel only"),
            ("B", "Blue", "Use blue channel only"),
        ],
        default="RGB",
        description="Mask source input channel",
    )

    # ========== TRANSFORM / VECTOR SETTINGS ==========
    texcoord_type: EnumProperty(
        name="Texture Coordinate",
        items=[
            ("UV", "UV", "UV coordinates"),
            ("GENERATED", "Generated", "Generated coordinates"),
            ("OBJECT", "Object", "Object coordinates"),
            ("DECAL", "Decal", "Decal projection"),
            ("CAMERA", "Camera", "Camera coordinates"),
            ("WINDOW", "Window", "Window coordinates"),
            ("NORMAL", "Normal", "Normal coordinates"),
            ("REFLECTION", "Reflection", "Reflection coordinates"),
        ],
        default="UV",
        description="Texture coordinate type",
    )

    uv_name: StringProperty(
        name="UV Map", default="", description="UV map to use for UV coordinates"
    )

    projection_blend: FloatProperty(
        name="Projection Blend",
        default=0.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        description="Box projection blend amount",
    )

    translation: FloatVectorProperty(
        name="Translation",
        size=3,
        precision=3,
        default=(0.0, 0.0, 0.0),
        description="Position offset",
    )

    rotation: FloatVectorProperty(
        name="Rotation",
        size=3,
        precision=3,
        unit="ROTATION",
        default=(0.0, 0.0, 0.0),
        description="Rotation",
    )

    scale: FloatVectorProperty(
        name="Scale", size=3, precision=3, default=(1.0, 1.0, 1.0), description="Scale"
    )

    # ========== VECTOR EFFECTS ==========
    enable_blur_vector: BoolProperty(
        name="Enable Blur Vector",
        default=False,
        description="Enable vector blur for mask",
    )

    blur_vector_factor: FloatProperty(
        name="Blur Factor",
        default=1.0,
        min=0.0,
        max=100.0,
        description="Blur vector factor",
    )

    # ========== MASK TYPE SPECIFIC ==========
    object_index: IntProperty(
        name="Object Index",
        default=0,
        min=0,
        description="Object index for object index mask",
    )

    color_id: FloatVectorProperty(
        name="Color ID",
        size=4,
        subtype="COLOR",
        default=(1.0, 1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        description="Color ID for color ID mask",
    )

    hemi_space: EnumProperty(
        name="Fake Lighting Space",
        items=[
            ("OBJECT", "Object", "Object space"),
            ("WORLD", "World", "World space"),
            ("CAMERA", "Camera", "Camera space"),
        ],
        default="OBJECT",
        description="Fake lighting space for hemisphere mask",
    )

    edge_detect_radius: FloatProperty(
        name="Edge Detect Radius",
        default=0.05,
        min=0.0,
        max=10.0,
        precision=3,
        description="Edge detection radius",
    )

    ao_distance: FloatProperty(
        name="AO Distance",
        default=1.0,
        min=0.0,
        max=10.0,
        description="Ambient occlusion distance",
    )

    decal_distance_value: FloatProperty(
        name="Decal Distance",
        default=0.5,
        min=0.0,
        max=100.0,
        precision=3,
        description="Distance for decal mask",
    )

    # ========== BAKING ==========
    use_baked: BoolProperty(
        name="Use Baked", default=False, description="Use baked mask"
    )

    use_temp_bake: BoolProperty(
        name="Use Temp Bake", default=False, description="Use temporary bake"
    )


class MixarLayer(bpy.types.PropertyGroup):
    """Property group for individual layer"""

    # Identity
    name: StringProperty(name="Layer Name", default="Layer")

    id_name: StringProperty(
        name="ID", default="", description="Unique identifier for this layer"
    )

    layer_type: EnumProperty(
        name="Layer Type",
        items=[
            ("FILL", "Fill", "Fill Layer"),
            ("PAINT", "Paint", "Paint Layer"),
        ],
        default="FILL",
    )

    # Visual state
    visible: BoolProperty(
        name="Visible",
        default=True,
        description="Layer visibility",
        update=update_layer_visible
    )

    focused: BoolProperty(
        name="Focused", default=False, description="Layer is currently focused/selected"
    )

    # Layer settings
    opacity: FloatProperty(
        name="Opacity",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        description="Layer opacity",
        update=update_layer_opacity
    )

    blend_mode: EnumProperty(
        name="Blend Mode",
        items=[
            ("MIX", "Mix", "Mix"),
            ("ADD", "Add", "Add"),
            ("MULTIPLY", "Multiply", "Multiply"),
            ("SUBTRACT", "Subtract", "Subtract"),
            ("SCREEN", "Screen", "Screen"),
            ("OVERLAY", "Overlay", "Overlay"),
        ],
        default="MIX",
        description="How this layer blends with layers below",
        update=update_layer_blend_mode
    )

    # Backend references (Mixar backend integration)
    mixar_layer_idx: IntProperty(
        name="Mixar Layer Index",
        default=-1,
        description="Index in Mixar mixar_mp.layers collection",
    )

    mixar_group_node: StringProperty(
        name="Mixar Group Node", default="", description="Name of the Mixar group node"
    )

    # Update prevention flag (Mixar Paint pattern)
    updating_property: BoolProperty(
        name="Updating Property",
        default=False,
        description="Internal flag to prevent circular update loops during property callbacks",
    )


# Classes for registration
classes = (
    MixarLayerChannel,
    MixarLayerMask,
    MixarLayer,
)


# Removed automatic layer initialization - user must click "Create layer based material"


def register():
    """Register property classes and scene properties.

    This function is idempotent - safe to call multiple times.
    """
    # Register PropertyGroup classes
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise

    # Add channels and masks as collection properties to layer
    if not hasattr(MixarLayer, 'channels'):
        MixarLayer.channels = CollectionProperty(
            type=MixarLayerChannel,
            name="Channels",
            description="Layer channels (Color, Roughness, Metallic, Normal, etc.)",
        )

    if not hasattr(MixarLayer, 'masks'):
        MixarLayer.masks = CollectionProperty(
            type=MixarLayerMask, name="Masks", description="Layer masks"
        )

    # Register scene properties
    if not hasattr(bpy.types.Scene, 'mixar_layers'):
        bpy.types.Scene.mixar_layers = CollectionProperty(type=MixarLayer)
    if not hasattr(bpy.types.Scene, 'mixar_active_layer_index'):
        bpy.types.Scene.mixar_active_layer_index = IntProperty(default=0)


def unregister():
    """Unregister property classes and scene properties"""
    # Remove scene properties
    if hasattr(bpy.types.Scene, 'mixar_active_layer_index'):
        del bpy.types.Scene.mixar_active_layer_index
    if hasattr(bpy.types.Scene, 'mixar_layers'):
        del bpy.types.Scene.mixar_layers

    # Remove collection properties from layer
    if hasattr(MixarLayer, 'masks'):
        del MixarLayer.masks
    if hasattr(MixarLayer, 'channels'):
        del MixarLayer.channels

    # Unregister classes in reverse order
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
