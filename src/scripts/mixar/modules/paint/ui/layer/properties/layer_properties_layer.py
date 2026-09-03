# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Additional layer property definitions for MLayer class.

This module contains property definitions for layer-specific settings
including hemi/fake lighting, transforms, sources, masks, and UI state.
"""

from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)

from ...mask.mask_properties import MLayerMask
from ...mask.mask_properties_helper import update_enable_layer_masks
from ...modifier.modifier_properties import MPaintModifier
from ...list_item.list_item_utils import update_expand_subitems

# Import callbacks
from .layer_properties_callbacks import (
    update_hemi_camera_ray_mask,
    update_hemi_space,
    update_hemi_use_prev_normal,
    update_layer_blur_vector,
    update_layer_blur_vector_factor,
    update_layer_transform,
    update_layer_uniform_scale_enabled,
    update_layer_use_baked,
    update_uv_name,
)

from ....utils.constants import hemi_space_items


def register_layer_properties(cls):
    """Register additional layer properties on MLayer class.

    This function adds hemi lighting, transform, source, and mask properties
    to the provided class using __annotations__.

    Args:
        cls: The PropertyGroup class to add properties to.
    """
    # Fake lighting (hemi) properties
    # We need to use bpy.props directly here
    from bpy.props import EnumProperty

    cls.__annotations__["hemi_space"] = EnumProperty(
        name="Fake Lighting Space",
        description="Fake lighting space",
        items=hemi_space_items,
        default="OBJECT",
        update=update_hemi_space,
    )

    cls.__annotations__["hemi_vector"] = FloatVectorProperty(
        name="Cache Hemi vector",
        size=3,
        precision=3,
        default=(0.0, 0.0, 1.0)
    )

    cls.__annotations__["hemi_camera_ray_mask"] = BoolProperty(
        name="Camera Ray Mask",
        description="Use Camera Ray value so the back of the mesh won't be affected by fake lighting",
        default=False,
        update=update_hemi_camera_ray_mask,
    )

    cls.__annotations__["hemi_use_prev_normal"] = BoolProperty(
        name="Use previous Normal",
        description="Take account previous Normal",
        default=False,
        update=update_hemi_use_prev_normal,
    )

    cls.__annotations__["bump_process"] = StringProperty(default="")

    # Image tracking
    cls.__annotations__["image_name"] = StringProperty(default="")

    # Segment names for image atlas
    cls.__annotations__["segment_name"] = StringProperty(default="")
    cls.__annotations__["baked_segment_name"] = StringProperty(default="")

    # UV settings
    cls.__annotations__["uv_name"] = StringProperty(
        name="UV Name",
        description="UV Name to use for layer coordinate",
        default="",
        update=update_uv_name,
    )

    cls.__annotations__["baked_uv_name"] = StringProperty(
        name="Baked UV Name",
        description="UV Name to use for layer coordinate",
        default="",
    )

    # Parent index
    cls.__annotations__["parent_idx"] = IntProperty(default=-1)

    # Transform properties
    cls.__annotations__["translation"] = FloatVectorProperty(
        name="Translation",
        size=3,
        precision=3,
        default=(0.0, 0.0, 0.0),
        update=update_layer_transform,
    )

    cls.__annotations__["rotation"] = FloatVectorProperty(
        name="Rotation",
        subtype="AXISANGLE",
        size=3,
        precision=3,
        unit="ROTATION",
        default=(0.0, 0.0, 0.0),
        update=update_layer_transform,
    )

    cls.__annotations__["scale"] = FloatVectorProperty(
        name="Scale",
        size=3,
        precision=3,
        default=(1.0, 1.0, 1.0),
        update=update_layer_transform,
    )

    # Blur vector settings
    cls.__annotations__["enable_blur_vector"] = BoolProperty(
        name="Enable Blur Vector",
        description="Enable blur vector",
        default=False,
        update=update_layer_blur_vector,
    )

    cls.__annotations__["blur_vector_factor"] = FloatProperty(
        name="Blur Vector Factor",
        description="Blur vector factor",
        default=1.0,
        min=0.0,
        max=100.0,
        update=update_layer_blur_vector_factor,
    )

    # Decal settings
    cls.__annotations__["decal_distance_value"] = FloatProperty(
        name="Decal Distance",
        description="Distance between surface and the decal object",
        min=0.0,
        max=100.0,
        default=0.5,
        precision=3,
    )

    # Baked layer settings
    cls.__annotations__["use_baked"] = BoolProperty(
        name="Use Baked",
        description="Use baked layer image",
        default=False,
        update=update_layer_use_baked,
    )

    # Source node names
    cls.__annotations__["source"] = StringProperty(default="")
    cls.__annotations__["source_n"] = StringProperty(default="")
    cls.__annotations__["source_s"] = StringProperty(default="")
    cls.__annotations__["source_e"] = StringProperty(default="")
    cls.__annotations__["source_w"] = StringProperty(default="")
    cls.__annotations__["source_group"] = StringProperty(default="")
    cls.__annotations__["baked_source"] = StringProperty(default="")
    cls.__annotations__["source_temp"] = StringProperty(default="")

    # Linear node
    cls.__annotations__["linear"] = StringProperty(default="")

    # Fix nodes
    cls.__annotations__["flip_y"] = StringProperty(default="")
    cls.__annotations__["divider_alpha"] = StringProperty(default="")

    # Layer type cache
    cls.__annotations__["cache_brick"] = StringProperty(default="")
    cls.__annotations__["cache_checker"] = StringProperty(default="")
    cls.__annotations__["cache_gradient"] = StringProperty(default="")
    cls.__annotations__["cache_magic"] = StringProperty(default="")
    cls.__annotations__["cache_musgrave"] = StringProperty(default="")
    cls.__annotations__["cache_noise"] = StringProperty(default="")
    cls.__annotations__["cache_gabor"] = StringProperty(default="")
    cls.__annotations__["cache_voronoi"] = StringProperty(default="")
    cls.__annotations__["cache_wave"] = StringProperty(default="")
    cls.__annotations__["cache_color"] = StringProperty(default="")
    cls.__annotations__["cache_image"] = StringProperty(default="")
    cls.__annotations__["cache_vcol"] = StringProperty(default="")
    cls.__annotations__["cache_hemi"] = StringProperty(default="")

    # UV node names
    cls.__annotations__["uv_neighbor"] = StringProperty(default="")
    cls.__annotations__["uv_neighbor_1"] = StringProperty(default="")
    cls.__annotations__["uv_map"] = StringProperty(default="")
    cls.__annotations__["mapping"] = StringProperty(default="")
    cls.__annotations__["baked_mapping"] = StringProperty(default="")
    cls.__annotations__["texcoord"] = StringProperty(default="")
    cls.__annotations__["blur_vector"] = StringProperty(default="")

    # Uniform scale settings
    cls.__annotations__["enable_uniform_scale"] = BoolProperty(
        name="Enable Uniform Scale",
        description="Use the same value for all scale components",
        default=False,
        update=update_layer_uniform_scale_enabled,
    )

    cls.__annotations__["uniform_scale_value"] = FloatProperty(default=1)

    # Decal processing node
    cls.__annotations__["decal_process"] = StringProperty(default="")

    # Vector node names
    cls.__annotations__["tangent"] = StringProperty(default="")
    cls.__annotations__["bitangent"] = StringProperty(default="")
    cls.__annotations__["tangent_flip"] = StringProperty(default="")
    cls.__annotations__["bitangent_flip"] = StringProperty(default="")

    # Modifiers
    cls.__annotations__["modifiers"] = CollectionProperty(type=MPaintModifier)
    cls.__annotations__["mod_group"] = StringProperty(default="")
    cls.__annotations__["mod_group_1"] = StringProperty(default="")

    # Mask settings
    cls.__annotations__["enable_masks"] = BoolProperty(
        name="Enable Layer Masks",
        description="Enable layer masks",
        default=True,
        update=update_enable_layer_masks,
    )

    cls.__annotations__["masks"] = CollectionProperty(type=MLayerMask)

    # Per-layer UI state
    cls.__annotations__["expand_masks"] = BoolProperty(
        name="Expand Masks",
        description="Show masks nested under this layer",
        default=False,
    )

    cls.__annotations__["expand_children"] = BoolProperty(
        name="Expand Children",
        description="Show child layers inside this group",
        default=True,  # Groups expanded by default
    )

    cls.__annotations__["expand_subitems"] = BoolProperty(
        name="Expand Subitems",
        description="Expand subitems",
        default=False,
        update=update_expand_subitems,
    )
