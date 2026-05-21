# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

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

from ...core.modifier.mask_modifier import mask_modifier_type_items
from ...utils.common import get_addon_title
from ...utils.constants import (
    hemi_space_items,
    mask_texcoord_type_items,
    mask_type_items,
    voronoi_feature_items,
)
from ...utils.statics import entity_input_items, mask_blend_type_items
from ..mask_modifier.mask_modifier_properties import MMaskModifier
from .mask_properties_helper import (
    update_layer_mask_channel_enable,
    update_layer_mask_enable,
    update_mask_active_edit,
    update_mask_blend_type,
    update_mask_blur_vector,
    update_mask_hemi_camera_ray_mask,
    update_mask_hemi_space,
    update_mask_hemi_use_prev_normal,
    update_mask_name,
    update_mask_source_input,
    update_mask_transform,
    update_mask_uniform_scale_enabled,
    update_mask_use_baked,
    update_mask_uv_name,
    update_mask_voronoi_feature,
)
from .mask_properties_helper import (
    update_mask_edge_detect_radius,
    update_mask_intensity,
    update_mask_object_index,
)
from .mask_utils import update_mask_texcoord_type


class MLayerMaskChannel(bpy.types.PropertyGroup):
    enable: BoolProperty(
        name="Enable Mask Channel",
        description="Mask will affect this channel",
        default=True,
        update=update_layer_mask_channel_enable,
    )

    # Multiply between mask channels
    mix: StringProperty(default="")

    # Pure mask without any extra multiplier or uv shift, useful for height process
    mix_pure: StringProperty(default="")

    # Remaining masks after chain
    mix_remains: StringProperty(default="")

    # Normal and height has its own alpha if using group, this one is for normal
    mix_normal: StringProperty(default="")

    # ... and this one for vector displacement
    mix_vdisp: StringProperty(default="")

    # To limit mix value to not go above original channel value, useful for group layer
    mix_limit: StringProperty(default="")
    mix_limit_normal: StringProperty(default="")

    # Bump related
    # mix_n : StringProperty(default='')
    # mix_s : StringProperty(default='')
    # mix_e : StringProperty(default='')
    # mix_w : StringProperty(default='')

    # UI related
    expand_content: BoolProperty(default=False)


class MLayerMask(bpy.types.PropertyGroup):

    name: StringProperty(default="", update=update_mask_name)

    halt_update: BoolProperty(default=False)

    group_node: StringProperty(default="")

    enable: BoolProperty(
        name="Enable Mask",
        description="Enable mask",
        default=True,
        update=update_layer_mask_enable,
    )

    active_edit: BoolProperty(
        name="Active Mask",
        description="Active mask for Blender's paint mode and edit mode, or "
        + get_addon_title()
        + "'s Mask preview mode",
        default=False,
        update=update_mask_active_edit,
    )

    source_input: EnumProperty(
        name="Mask Source Input",
        description="Source input for mask",
        items=entity_input_items,
        update=update_mask_source_input,
    )

    # active_vcol_edit : BoolProperty(
    #        name='Active vertex color for editing',
    #        description='Active vertex color for editing',
    #        default=False,
    #        update=update_mask_active_vcol_edit)

    type: EnumProperty(name="Mask Type", items=mask_type_items, default="IMAGE")

    texcoord_type: EnumProperty(
        name="Mask Coordinate Type",
        description="Mask Coordinate Type",
        items=mask_texcoord_type_items,
        default="UV",
        # Using a lambda because update function is expected to have an arity of 2
        update=lambda self, context: update_mask_texcoord_type(self, context),
    )

    original_texcoord: EnumProperty(
        name="Original Layer Coordinate Type",
        items=mask_texcoord_type_items,
        default="UV",
    )

    original_image_extension: StringProperty(
        name="Original Image Extension Type", default=""
    )

    modifier_type: EnumProperty(
        name="Mask Modifier Type", items=mask_modifier_type_items, default="INVERT"
    )

    hemi_space: EnumProperty(
        name="Fake Lighting Space",
        description="Fake lighting space",
        items=hemi_space_items,
        default="OBJECT",
        update=update_mask_hemi_space,
    )

    hemi_camera_ray_mask: BoolProperty(
        name="Camera Ray Mask",
        description="Use Camera Ray value so the back of the mesh won't be affected by fake lighting",
        default=False,
        update=update_mask_hemi_camera_ray_mask,
    )

    hemi_use_prev_normal: BoolProperty(
        name="Use previous Normal",
        description="Take account previous Normal",
        default=False,
        update=update_mask_hemi_use_prev_normal,
    )

    uv_name: StringProperty(
        name="UV Name",
        description="UV Name to use for mask coordinate",
        default="",
        update=update_mask_uv_name,
    )

    baked_uv_name: StringProperty(
        name="Baked UV Name",
        description="UV Name to use for baked mask coordinate",
        default="",
    )

    blend_type: EnumProperty(
        name="Blend",
        items=mask_blend_type_items,
        default=3,
        update=update_mask_blend_type,
    )

    intensity_value: FloatProperty(
        name="Mask Opacity",
        description="Mask opacity",
        subtype="FACTOR",
        default=1.0,
        min=0.0,
        max=1.0,
        precision=3,
        update=update_mask_intensity,
    )

    # Transform
    translation: FloatVectorProperty(
        name="Translation",
        size=3,
        precision=3,
        default=(0.0, 0.0, 0.0),
        update=update_mask_transform,
    )

    rotation: FloatVectorProperty(
        name="Rotation",
        subtype="AXISANGLE",
        size=3,
        precision=3,
        unit="ROTATION",
        default=(0.0, 0.0, 0.0),
        update=update_mask_transform,
    )

    scale: FloatVectorProperty(
        name="Scale",
        size=3,
        precision=3,
        default=(1.0, 1.0, 1.0),
        update=update_mask_transform,
    )

    enable_blur_vector: BoolProperty(
        name="Enable Blur Vector",
        description="Enable blur vector",
        default=False,
        update=update_mask_blur_vector,
    )

    blur_vector_factor: FloatProperty(
        name="Blur Vector Factor",
        description="Mask Intensity Factor",
        default=1.0,
        min=0.0,
        max=100.0,
        precision=3,
    )

    decal_distance_value: FloatProperty(
        name="Decal Distance",
        description="Distance between surface and the decal object",
        min=0.0,
        max=100.0,
        default=0.5,
        precision=3,
    )

    color_id: FloatVectorProperty(
        name="Color ID",
        size=3,
        subtype="COLOR",
        default=(1.0, 0.0, 1.0),
        min=0.0,
        max=1.0,
    )

    use_baked: BoolProperty(
        name="Use Baked",
        description="Use baked image rather generated mask",
        default=False,
        update=update_mask_use_baked,
    )

    segment_name: StringProperty(default="")
    baked_segment_name: StringProperty(default="")

    channels: CollectionProperty(type=MLayerMaskChannel)

    modifiers: CollectionProperty(type=MMaskModifier)

    # For object index
    object_index: IntProperty(
        name="Object Index",
        description="Object Pass Index",
        default=0,
        min=0,
        update=update_mask_object_index,
    )

    # For temporary bake
    use_temp_bake: BoolProperty(
        name="Use Temporary Bake",
        description="Use temporary bake, it can be useful to prevent glitching with cycles",
        default=False,
    )

    original_type: EnumProperty(
        name="Original Mask Type", items=mask_type_items, default="IMAGE"
    )

    # For fake lighting

    hemi_vector: FloatVectorProperty(
        name="Cache Hemi vector", size=3, precision=3, default=(0.0, 0.0, 1.0)
    )

    # For edge detection
    edge_detect_radius: FloatProperty(
        name="Edge Detect Radius",
        description="Edge detect radius",
        default=0.05,
        min=0.0,
        max=10.0,
        precision=3,
        update=update_mask_edge_detect_radius,
    )

    # For AO
    ao_distance: FloatProperty(
        name="Ambient Occlusion Distance",
        description="Ambient occlusion distance",
        default=1.0,
        min=0.0,
        max=10.0,
    )

    # Specific for voronoi
    voronoi_feature: EnumProperty(
        name="Voronoi Feature",
        description="The voronoi feature that will be used for compute",
        items=voronoi_feature_items,
        default="F1",
        update=update_mask_voronoi_feature,
    )

    # Nodes
    source: StringProperty(default="")
    source_n: StringProperty(default="")
    source_s: StringProperty(default="")
    source_e: StringProperty(default="")
    source_w: StringProperty(default="")

    baked_source: StringProperty(default="")

    # Mask type cache
    cache_brick: StringProperty(default="")
    cache_checker: StringProperty(default="")
    cache_gradient: StringProperty(default="")
    cache_magic: StringProperty(default="")
    cache_musgrave: StringProperty(default="")
    cache_noise: StringProperty(default="")
    cache_gabor: StringProperty(default="")
    cache_voronoi: StringProperty(default="")
    cache_wave: StringProperty(default="")
    cache_color: StringProperty(default="")

    cache_image: StringProperty(default="")
    cache_vcol: StringProperty(default="")
    cache_hemi: StringProperty(default="")

    cache_modifier_ramp: StringProperty(default="")
    cache_modifier_curve: StringProperty(default="")

    uv_map: StringProperty(default="")
    uv_neighbor: StringProperty(default="")
    mapping: StringProperty(default="")
    baked_mapping: StringProperty(default="")
    blur_vector: StringProperty(default="")
    separate_color_channels: StringProperty(default="")

    enable_uniform_scale: BoolProperty(
        name="Enable Uniform Scale",
        description="Use the same value for all scale components",
        default=False,
        update=update_mask_uniform_scale_enabled,
    )

    uniform_scale_value: FloatProperty(default=1)

    decal_process: StringProperty(default="")
    texcoord: StringProperty(default="")
    decal_alpha: StringProperty(default="")
    decal_alpha_n: StringProperty(default="")
    decal_alpha_s: StringProperty(default="")
    decal_alpha_e: StringProperty(default="")
    decal_alpha_w: StringProperty(default="")

    linear: StringProperty(default="")

    # Only useful for merging mask for now
    mix: StringProperty(default="")

    need_temp_uv_refresh: BoolProperty(default=False)

    tangent: StringProperty(default="")
    bitangent: StringProperty(default="")
    tangent_flip: StringProperty(default="")
    bitangent_flip: StringProperty(default="")

    # UI related
    expand_content: BoolProperty(default=False)
    expand_channels: BoolProperty(default=False)
    expand_source: BoolProperty(default=False)
    expand_vector: BoolProperty(default=False)
    expand_modifiers: BoolProperty(default=False)
