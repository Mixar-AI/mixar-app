# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Property declarations for MBakeToLayer operator."""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)

from ....utils.constants import (
    bake_type_items,
    interpolation_type_items,
    normal_blend_items,
)
from ....utils.statics import blend_type_items
from .bake_to_layer_operators_helper import update_bake_to_layer_uv_map


# -------------------------------------------------------------------------
# Wrapper functions with delayed imports to avoid circular imports
# -------------------------------------------------------------------------
def channel_items(self, context):
    """Wrapper for channel_items with delayed import."""
    from ...layer.helpers.layer_enum_helpers import channel_items as _impl
    return _impl(self, context)


def get_normal_map_type_items(self, context):
    """Wrapper for get_normal_map_type_items with delayed import."""
    from ...layer.helpers.layer_enum_helpers import get_normal_map_type_items as _impl
    return _impl(self, context)


def update_use_udim(self, context):
    """Disable image atlas when UDIM is disabled."""
    if not self.use_udim:
        self.use_image_atlas = False


class BakeToLayerProperties:
    """Mixin class containing properties for MBakeToLayer operator."""

    name: StringProperty(default="")

    uv_map: StringProperty(default="", update=update_bake_to_layer_uv_map)
    uv_map_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    uv_map_1: StringProperty(default="")

    interpolation: EnumProperty(
        name="Image Interpolation Type",
        description="Image interpolation type",
        items=interpolation_type_items,
        default="Linear",
    )

    # For choosing overwrite entity from list
    overwrite_choice: BoolProperty(
        name="Overwrite available layer",
        description="Overwrite available layer",
        default=False,
    )

    # For rebake button
    overwrite_current: BoolProperty(default=False)

    overwrite_name: StringProperty(default="")
    overwrite_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    overwrite_image_name: StringProperty(default="")
    overwrite_segment_name: StringProperty(default="")

    type: EnumProperty(
        name="Bake Type", description="Bake Type", items=bake_type_items, default="AO"
    )

    # Other objects props

    use_cage: BoolProperty(
        name="Cage Object",
        description="Cast rays to active material objects from a cage",
        default=False,
    )

    cage_object_name: StringProperty(
        name="Cage Object",
        description="Object to use as cage instead of calculating the cage from the active object with cage extrusion",
        default="",
    )

    cage_object_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    cage_extrusion: FloatProperty(
        name="Cage Extrusion",
        description="Inflate the active object by the specified distance for baking. This helps matching to points nearer to the outside of the selected object meshes",
        default=0.2,
        min=0.0,
        max=1.0,
    )

    max_ray_distance: FloatProperty(
        name="Max Ray Distance",
        description="The maximum ray distance for matching points between the active and selected objects. If zero, there is no limit",
        default=0.2,
        min=0.0,
        max=1.0,
    )

    normalize: BoolProperty(
        name="Normalize Bake Result",
        description="Normalize the bake result",
        default=True,
    )

    # Position Props
    position_space: EnumProperty(
        name="Position Space",
        description="Which space to bake position in",
        items=(
            ("OBJECT", "Object Space", "Position relative to object origin"),
            ("WORLD", "World Space", "Position in world space"),
        ),
        default="OBJECT",
    )

    position_normalize: BoolProperty(
        name="Normalize Position",
        description="Normalize position values using bounding box (0-1 range)",
        default=True,
    )

    # AO Props
    ao_distance: FloatProperty(default=1.0)

    # Bevel Props
    bevel_samples: IntProperty(default=4, min=2, max=16)
    bevel_radius: FloatProperty(default=0.05, min=0.0, max=1000.0)

    multires_base: IntProperty(default=1, min=0, max=16)

    target_type: EnumProperty(
        name="Target Bake Type",
        description="Target Bake Type",
        items=(
            ("PREVIEW", "Preview Only", "Save image without creating layer"),
            ("LAYER", "Layer", "Create new layer with baked image"),
            ("MASK", "Mask", "Create new mask with baked image"),
        ),
        default="PREVIEW",
    )

    apply_to_fill_layer: BoolProperty(
        name="Apply to Fill Layer",
        description="Apply baked AO to existing Fill layer's AO channel (internal use)",
        default=False,
        options={'HIDDEN'},
    )

    fxaa: BoolProperty(
        name="Use FXAA",
        description="Use FXAA on baked image (doesn't work with float images)",
        default=True,
    )

    ssaa: BoolProperty(
        name="Use SSAA", description="Use Supersample AA on baked image", default=False
    )

    denoise: BoolProperty(
        name="Use Denoise", description="Use Denoise on baked image", default=True
    )

    channel_idx: EnumProperty(
        name="Channel",
        description="Channel of new layer, can be changed later",
        items=channel_items,
    )

    blend_type: EnumProperty(
        name="Blend",
        items=blend_type_items,
    )

    normal_blend_type: EnumProperty(
        name="Normal Blend Type", items=normal_blend_items, default="MIX"
    )

    normal_map_type: EnumProperty(
        name="Normal Map Type",
        description="Normal map type of this layer",
        items=get_normal_map_type_items,
    )

    hdr: BoolProperty(name="32 bit Float", default=True)

    use_baked_disp: BoolProperty(
        name="Use Displacement Setup",
        description="Use displacement setup, this will also apply subdiv setup on object",
        default=False,
    )

    flip_normals: BoolProperty(
        name="Flip Normals", description="Flip normal of mesh", default=False
    )

    only_local: BoolProperty(
        name="Only Local",
        description="Only bake local ambient occlusion",
        default=False,
    )

    subsurf_influence: BoolProperty(
        name="Subsurf / Multires Influence",
        description="Take account subsurf or multires when baking cavity",
        default=True,
    )

    force_bake_all_polygons: BoolProperty(
        name="Force Bake all Polygons",
        description="Force bake all polygons, useful if material is not using direct polygon (ex: solidify material)",
        default=False,
    )

    use_image_atlas: BoolProperty(
        name="Use Image Atlas", description="Use Image Atlas", default=False
    )

    use_udim: BoolProperty(
        name="Use UDIM Tiles", description="Use UDIM Tiles", default=False
    )
