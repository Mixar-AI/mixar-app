# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""MLayerChannel property group definition.

This module defines the MLayerChannel PropertyGroup class with all
channel-specific settings including blend modes, overrides, and normal/bump.
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

from ....utils.constants import (
    channel_override_1_type_items,
    get_channel_override_type_items,
    normal_blend_items,
    normal_space_items,
    voronoi_feature_items,
)
from ....utils.statics import blend_type_items, entity_input_items
from ...modifier.modifier_properties import MPaintModifier
from ...normal_map_modifier.normal_map_modifier_properties import MNormalMapModifier

# Import callback wrappers
from .layer_properties_callbacks import (
    get_normal_map_type_items,
    update_blend_type,
    update_bump_distance,
    update_bump_midlevel,
    update_channel_active_edit,
    update_channel_enable,
    update_channel_intensity_value,
    update_flip_backface_normal,
    update_image_flip_y,
    update_layer_channel_override,
    update_layer_channel_override_1,
    update_layer_channel_override_vcol_name,
    update_layer_channel_use_clamp,
    update_layer_channel_vdisp_flip_yz,
    update_layer_channel_voronoi_feature,
    update_layer_input,
    update_normal_map_type,
    update_normal_space,
    update_override_color_value,
    update_write_height,
)


class MLayerChannel(bpy.types.PropertyGroup):
    """Property group for layer channel settings."""

    # Basic channel settings
    enable: BoolProperty(
        name="Enable Layer Channel",
        description="Enable layer channel",
        default=True,
        update=update_channel_enable,
    )
    layer_input: EnumProperty(
        name="Layer Input",
        description="Input for layer channel",
        items=entity_input_items,
        update=update_layer_input,
    )
    gamma_space: BoolProperty(
        name="Gamma Space",
        description="Make sure layer input is in linear space",
        default=False,
        update=update_layer_input,
    )
    use_clamp: BoolProperty(
        name="Use Clamp",
        description="Clamp result to 0..1 range",
        default=False,
        update=update_layer_channel_use_clamp,
    )

    # Blend settings
    normal_map_type: EnumProperty(
        name="Normal Map Type",
        items=get_normal_map_type_items,
        update=update_normal_map_type,
    )
    blend_type: EnumProperty(
        name="Blend",
        description="Blend type of layer channel",
        items=blend_type_items,
        update=update_blend_type,
    )
    normal_blend_type: EnumProperty(
        name="Normal Blend Type",
        description="Blend type of layer normal channel",
        items=normal_blend_items,
        default="MIX",
        update=update_blend_type,
    )
    normal_space: EnumProperty(
        name="Normal Space",
        description="Space of the normal map",
        items=normal_space_items,
        default="TANGENT",
        update=update_normal_space,
    )
    height_blend_type: EnumProperty(
        name="Height Blend Type",
        items=normal_blend_items,
        default="MIX",
        update=update_blend_type,
    )
    intensity_value: FloatProperty(
        name="Layer Channel Opacity",
        description="Layer channel opacity",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        precision=3,
        update=update_channel_intensity_value,
    )

    # Modifiers
    modifiers: CollectionProperty(type=MPaintModifier)
    modifiers_1: CollectionProperty(type=MNormalMapModifier)

    # Override properties
    override: BoolProperty(
        name="Enable Override",
        description="Use override value for this channel",
        default=False,
        update=update_layer_channel_override,
    )
    override_type: EnumProperty(
        items=get_channel_override_type_items,
        update=update_layer_channel_override,
    )
    override_color: FloatVectorProperty(
        name="Override Color",
        description="Override color value",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(0.5, 0.5, 0.5),
        update=update_override_color_value,
    )
    override_value: FloatProperty(
        name="Override Value",
        description="Override value for this channel",
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        default=1.0,
        update=update_override_color_value,
    )
    override_vcol_name: StringProperty(
        name="Vertex Color Name",
        description="Channel override vertex color name",
        default="",
        update=update_layer_channel_override_vcol_name,
    )
    voronoi_feature: EnumProperty(
        name="Voronoi Feature",
        description="Voronoi feature for compute",
        items=voronoi_feature_items,
        default="F1",
        update=update_layer_channel_voronoi_feature,
    )
    override_1: BoolProperty(
        name="Enable Override (Normal Map)",
        description="Override for normal map",
        default=False,
        update=update_layer_channel_override_1,
    )
    override_1_type: EnumProperty(
        items=channel_override_1_type_items,
        default="DEFAULT",
        update=update_layer_channel_override_1,
    )
    override_1_color: FloatVectorProperty(
        name="Override Color",
        description="Override color for normal map",
        subtype="COLOR",
        size=3,
        default=(0.5, 0.5, 1.0),
        min=0.0,
        max=1.0,
    )

    # Normal/bump properties
    invert_backface_normal: BoolProperty(
        default=False,
        update=update_flip_backface_normal,
    )
    bump_distance: FloatProperty(
        name="Bump Height Range",
        description="Bump height range (white = value, black = negative)",
        default=0.05,
        min=-1.0,
        max=1.0,
        precision=3,
        update=update_bump_distance,
    )
    bump_midlevel: FloatProperty(
        name="Bump Midlevel",
        description="Neutral bump value that causes no bump",
        default=0.5,
        min=0.0,
        max=1.0,
        precision=3,
        update=update_bump_midlevel,
    )
    bump_smooth_multiplier: FloatProperty(
        name="Smooth Bump Step Multiplier",
        description="Multiply the smooth bump step",
        default=1.0,
        min=0.1,
        max=10.0,
        precision=3,
    )
    normal_bump_distance: FloatProperty(
        name="Bump Height Range for normal",
        description="Bump height range for normal channel",
        default=0.00,
        min=-1.0,
        max=1.0,
        precision=3,
    )
    write_height: BoolProperty(
        name="Write Height",
        description="Write height data for displacement/parallax",
        default=False,
        update=update_write_height,
    )
    normal_write_height: BoolProperty(
        name="Write Normal Height",
        description="Write height for this normal layer channel",
        default=False,
        update=update_write_height,
    )
    normal_strength: FloatProperty(
        name="Normal Strength",
        description="Normal strength",
        default=1.0,
        min=0.0,
        max=100.0,
        precision=3,
    )
    vdisp_strength: FloatProperty(
        name="Vector Displacement Strength",
        description="Vector displacement strength",
        default=1.0,
        min=-10.0,
        max=10.0,
        precision=3,
    )
    vdisp_enable_flip_yz: BoolProperty(
        name="Vector Displacement Flip YZ Channel",
        description="Flip YZ channel value (blender compatibility)",
        default=True,
        update=update_layer_channel_vdisp_flip_yz,
    )
    image_flip_y: BoolProperty(
        name="Image Flip G",
        description="Image Flip G (for DirectX normal maps)",
        default=False,
        update=update_image_flip_y,
    )

    # Active edit properties
    active_edit: BoolProperty(
        name="Active Custom Data",
        description="Active custom data for paint/edit mode or preview",
        default=False,
        update=update_channel_active_edit,
    )
    active_edit_1: BoolProperty(
        name="Active Custom Normal Data",
        description="Active custom normal data for paint/edit mode or preview",
        default=False,
        update=update_channel_active_edit,
    )
    prev_active_edit_idx: IntProperty(
        name="Previous Active Edit Index",
        description="To store previous active edit index",
        default=0,
    )

    # UI expand states
    expand_bump_settings: BoolProperty(default=False)
    expand_intensity_settings: BoolProperty(default=False)
    expand_content: BoolProperty(default=False)
    expand_input_settings: BoolProperty(default=False)
    expand_blend_settings: BoolProperty(default=False)
    expand_source: BoolProperty(default=False)
    expand_source_1: BoolProperty(default=False)
    expand_modifiers: BoolProperty(default=False)


# Register node name properties from separate module
from .layer_properties_channel_nodes import register_channel_node_properties

register_channel_node_properties(MLayerChannel)

# Register transition properties from separate module
from .layer_properties_transition import register_transition_properties

register_transition_properties(MLayerChannel)
