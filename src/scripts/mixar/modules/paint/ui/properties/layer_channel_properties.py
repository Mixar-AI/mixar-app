# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer channel property group for Mixar layers system.

This module contains the MixarLayerChannel PropertyGroup which defines
all properties for individual layer channels (Color, Roughness, Metallic, Normal, etc.).
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)

from .layer_properties_callbacks import (
    update_channel_color_value,
    update_channel_scalar_value,
    update_channel_intensity,
    update_channel_enable,
    update_channel_blend_type,
    update_layer_channel_override,
    update_layer_channel_override_vcol_name,
)


class MixarLayerChannel(bpy.types.PropertyGroup):
    """Property group for individual layer channel"""

    # ========== BASIC CHANNEL SETTINGS ==========
    name: StringProperty(name="Channel Name", default="Channel")

    enable: BoolProperty(
        name="Enable Channel",
        default=True,
        description="Enable/disable this channel",
        update=update_channel_enable
    )

    # ========== CHANNEL INPUT ==========
    layer_input: EnumProperty(
        name="Layer Input",
        items=[
            ("RGB", "RGB", "Use RGB channels"),
            ("ALPHA", "Alpha", "Use alpha channel"),
            ("R", "Red", "Use red channel only"),
            ("G", "Green", "Use green channel only"),
            ("B", "Blue", "Use blue channel only"),
        ],
        default="RGB",
        description="Input for layer channel",
    )

    gamma_space: BoolProperty(
        name="Gamma Space",
        default=False,
        description="Ensure layer input is in linear space",
    )

    use_clamp: BoolProperty(
        name="Use Clamp", default=False, description="Clamp result to 0..1 range"
    )

    # ========== BLENDING ==========
    blend_type: EnumProperty(
        name="Blend Type",
        items=[
            ("MIX", "Mix", "Mix"),
            ("ADD", "Add", "Add"),
            ("MULTIPLY", "Multiply", "Multiply"),
            ("SUBTRACT", "Subtract", "Subtract"),
            ("SCREEN", "Screen", "Screen"),
            ("OVERLAY", "Overlay", "Overlay"),
            ("DARKEN", "Darken", "Darken"),
            ("LIGHTEN", "Lighten", "Lighten"),
            ("DIVIDE", "Divide", "Divide"),
            ("DIFFERENCE", "Difference", "Difference"),
            ("COLOR", "Color", "Color"),
            ("HUE", "Hue", "Hue"),
            ("SATURATION", "Saturation", "Saturation"),
            ("VALUE", "Value", "Value"),
        ],
        default="MIX",
        description="Blend type of layer channel",
        update=update_channel_blend_type
    )

    normal_blend_type: EnumProperty(
        name="Normal Blend Type",
        items=[
            ("MIX", "Mix", "Mix"),
            ("PARTIAL_DERIVATIVE", "Partial Derivative", "Partial Derivative"),
            ("WHITEOUT", "Whiteout", "Whiteout"),
            ("UDN", "UDN", "UDN"),
            ("OVERLAY", "Overlay", "Overlay"),
        ],
        default="MIX",
        description="Blend type for normal channels",
    )

    intensity_value: FloatProperty(
        name="Channel Opacity",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        precision=3,
        description="Channel opacity/intensity",
        update=lambda self, context: update_channel_intensity(self, context),
    )

    # ========== NODE REFERENCES (Mixar Paint pattern) ==========
    source_node_name: StringProperty(
        name="Source Node Name",
        default="",
        description="Name of the source node for this channel",
    )

    blend_node_name: StringProperty(
        name="Blend Node Name",
        default="",
        description="Name of the blend node (from backend ch.blend)",
    )

    intensity_node_name: StringProperty(
        name="Intensity Node Name",
        default="",
        description="Name of the intensity node (from backend ch.intensity)",
    )

    # ========== CHANNEL VALUES (for Fill Layers) ==========
    color_value: FloatVectorProperty(
        name="Color",
        subtype="COLOR",
        size=4,
        default=(0.8, 0.8, 0.8, 1.0),
        min=0.0,
        max=1.0,
        description="Color value for fill layer",
        update=lambda self, context: update_channel_color_value(self, context),
    )

    scalar_value: FloatProperty(
        name="Value",
        default=0.5,
        min=0.0,
        max=1.0,
        precision=3,
        description="Scalar value for fill layer (Roughness, Metallic, etc.)",
        update=lambda self, context: update_channel_scalar_value(self, context),
    )

    # ========== NORMAL MAP SETTINGS ==========
    normal_map_type: EnumProperty(
        name="Normal Map Type",
        items=[
            ("BUMP_MAP", "Bump Map", "Bump map"),
            ("NORMAL_MAP", "Normal Map", "Normal map"),
            ("BUMP_NORMAL_MAP", "Bump + Normal", "Bump and normal map combined"),
            ("VDM", "VDM", "Vector displacement map"),
        ],
        default="BUMP_MAP",
        description="Normal map type",
    )

    normal_space: EnumProperty(
        name="Normal Space",
        items=[
            ("TANGENT", "Tangent", "Tangent space"),
            ("OBJECT", "Object", "Object space"),
            ("WORLD", "World", "World space"),
        ],
        default="TANGENT",
        description="Normal map space",
    )

    normal_strength: FloatProperty(
        name="Normal Strength",
        default=1.0,
        min=0.0,
        max=10.0,
        precision=3,
        description="Normal map strength",
    )

    normal_bump_distance: FloatProperty(
        name="Bump Distance",
        default=0.1,
        min=0.0,
        max=10.0,
        precision=3,
        description="Bump height range",
    )

    normal_write_height: BoolProperty(
        name="Write Height",
        default=False,
        description="Write height data for displacement",
    )

    image_flip_y: BoolProperty(
        name="Flip Y",
        default=False,
        description="Flip Y channel (for DirectX normal maps)",
    )

    # ========== OVERRIDE SETTINGS ==========
    override: BoolProperty(
        name="Override",
        default=True,
        description="Enable channel override",
        update=update_layer_channel_override,
    )

    override_type: EnumProperty(
        name="Override Type",
        items=[
            ("DEFAULT", "Default", "Use default layer source"),
            ("IMAGE", "Image", "Use image override"),
            ("VCOL", "Vertex Color", "Use vertex color override"),
            ("COLOR", "Color", "Use fill color override"),
            ("VALUE", "Value", "Use scalar value override"),
        ],
        default="DEFAULT",
        description="Channel override type",
        update=update_layer_channel_override,
    )

    override_color: FloatVectorProperty(
        name="Override Color",
        description="Override color value for this channel",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(0.5, 0.5, 0.5),
    )

    override_value: FloatProperty(
        name="Override Value",
        description="Override value for this channel",
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        default=1.0,
    )

    override_vcol_name: StringProperty(
        name="Vertex Color Name",
        description="Channel override vertex color name",
        default="",
        update=update_layer_channel_override_vcol_name,
    )

    # ========== TRANSITION EFFECTS ==========
    enable_transition_bump: BoolProperty(
        name="Enable Transition Bump",
        default=False,
        description="Enable edge bump effect",
    )

    transition_bump_falloff: FloatProperty(
        name="Transition Bump Falloff",
        default=0.1,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        description="Transition bump falloff distance",
    )

    enable_transition_ramp: BoolProperty(
        name="Enable Transition Ramp",
        default=False,
        description="Enable color ramp at edges",
    )

    transition_ramp_intensity_value: FloatProperty(
        name="Transition Ramp Intensity",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        description="Transition ramp strength",
    )

    enable_transition_ao: BoolProperty(
        name="Enable Transition AO",
        default=False,
        description="Enable AO at transitions",
    )

    transition_ao_intensity: FloatProperty(
        name="Transition AO Intensity",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        description="Transition AO strength",
    )

    # ========== DISPLACEMENT/SUBDIVISION ==========
    enable_subdiv_setup: BoolProperty(
        name="Enable Displacement Setup",
        default=False,
        description="Enable displacement/subdivision setup",
    )

    # ========== PARALLAX ==========
    enable_parallax: BoolProperty(
        name="Enable Parallax",
        default=False,
        description="Enable parallax occlusion mapping",
    )

    parallax_num_of_layers: IntProperty(
        name="Parallax Layers",
        default=16,
        min=1,
        max=128,
        description="Number of parallax layers",
    )

    # ========== ALPHA SETTINGS ==========
    enable_alpha: BoolProperty(
        name="Enable Alpha",
        default=False,
        description="Enable transparency for this channel",
    )

    alpha_blend_mode: EnumProperty(
        name="Alpha Blend Mode",
        items=[
            ("BLEND", "Blend", "Alpha blend"),
            ("HASHED", "Hashed", "Alpha hashed"),
            ("CLIP", "Clip", "Alpha clip"),
        ],
        default="BLEND",
        description="Alpha blending mode",
    )

    # ========== BAKING ==========
    enable_bake_to_vcol: BoolProperty(
        name="Bake to Vertex Color",
        default=False,
        description="Bake this channel to vertex colors",
    )

    bake_to_vcol_name: StringProperty(
        name="Bake Vcol Name",
        default="",
        description="Target vertex color name for baking",
    )

    # ========== UI EXPANSION ==========
    expand_source: BoolProperty(
        name="Expand Source",
        default=False,
        description="Expand to show source image details",
    )

    expand_blend_settings: BoolProperty(
        name="Expand Blend Settings",
        default=False,
        description="Expand to show blend mode and opacity settings",
    )

    expand_modifiers: BoolProperty(
        name="Expand Modifiers",
        default=False,
        description="Expand to show channel modifiers",
    )
