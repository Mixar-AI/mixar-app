# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer property group definitions for the paint module.

Defines MLayer PropertyGroup class. MLayerChannel is imported from
layer_channel_properties.py. Related modules:
layer_properties_callbacks.py, layer_properties_channel_nodes.py,
layer_properties_transition.py, layer_properties_layer.py
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)

from ....utils.common import get_layer_type_items_callback
from ....utils.constants import (
    layer_source_type_items,
    layer_type_items,
    projection_axis_items,
    projection_type_items,
    texcoord_type_items,
    uv_extension_items,
    voronoi_feature_items,
)
from ....utils.statics import BLEND_TYPE_ITEMS
from ...mask.mask_properties import MLayerMask, MLayerMaskChannel
from ...mask_modifier.mask_modifier_properties import MMaskModifier
from ...normal_map_modifier.normal_map_modifier_properties import MNormalMapModifier

# Import MLayerChannel from its own module
from .layer_channel_properties import MLayerChannel

# Import callback wrappers
from .layer_properties_callbacks import (
    update_blend_linked,
    update_divide_rgb_by_alpha,
    update_image_flip_y,
    update_layer_color_chortcut,
    update_layer_edge_detect_radius,
    update_layer_enable,
    update_layer_intensity_value,
    update_layer_name,
    update_layer_projection,
    update_layer_source_type,
    update_linked_blend_type,
    update_projection_axis,
    update_projection_blend,
    update_projection_hardness,
    update_texcoord_type,
    update_uv_extension,
    update_voronoi_feature,
)


class MLayer(bpy.types.PropertyGroup):
    """Property group for paint layer settings."""

    # Schema version for migration (v1=legacy override, v2=unified source)
    schema_version: IntProperty(
        name="Schema Version",
        description="Layer schema version for migration",
        default=2,
    )

    name: StringProperty(
        name="Layer Name",
        description="Layer name",
        default="",
        update=update_layer_name,
    )

    enable: BoolProperty(
        name="Enable Layer",
        description="Enable layer",
        default=True,
        update=update_layer_enable,
    )

    channels: CollectionProperty(type=MLayerChannel)

    group_node: StringProperty(default="")
    trash_group_node: StringProperty(default="")
    depth_group_node: StringProperty(default="")

    type: EnumProperty(name="Layer Type", items=get_layer_type_items_callback)

    procedural_material_id: StringProperty(
        name="Procedural Material ID",
        description="ID of custom procedural material",
        default="",
    )

    source_type: EnumProperty(
        name="Source Type",
        description="Source type for fill layer",
        items=layer_source_type_items,
        default="SOLID_COLOR",
        update=update_layer_source_type,
    )

    projection_type: EnumProperty(
        name="Projection",
        description="Texture projection type",
        items=projection_type_items,
        default="UV",
        update=update_layer_projection,
    )

    projection_axis: EnumProperty(
        name="Axis",
        description="Projection axis for Planar/Cylindrical modes",
        items=projection_axis_items,
        default="Z",
        update=update_projection_axis,
    )

    intensity_value: FloatProperty(
        name="Layer Opacity",
        description="Layer opacity",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        precision=3,
        update=update_layer_intensity_value,
    )

    blend_linked: BoolProperty(
        name="Link Blend Modes",
        description="Use same blend mode for all channels",
        default=True,
        update=update_blend_linked,
    )

    linked_blend_type: EnumProperty(
        name="Blend Mode",
        description="Linked blend mode for all channels",
        items=BLEND_TYPE_ITEMS,
        default="MIX",
        update=update_linked_blend_type,
    )

    color_shortcut: BoolProperty(
        name="Color Shortcut on the list",
        description="Display color shortcut on the list",
        default=True,
        update=update_layer_color_chortcut,
    )

    texcoord_type: EnumProperty(
        name="Layer Coordinate Type",
        description="Layer Coordinate Type",
        items=texcoord_type_items,
        default="UV",
        update=update_texcoord_type,
    )

    original_texcoord: EnumProperty(
        name="Original Layer Coordinate Type",
        items=texcoord_type_items,
        default="UV",
    )

    original_image_extension: StringProperty(
        name="Original Image Extension Type",
        default="",
    )

    projection_blend: FloatProperty(
        name="Box Projection Blend",
        description="Amount of blend to use between sides",
        default=0.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=update_projection_blend,
    )

    projection_hardness: FloatProperty(
        name="Hardness",
        description="Triplanar blend sharpness (0=soft blend, 1=hard edges)",
        default=0.1,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=update_projection_hardness,
    )

    uv_extension: EnumProperty(
        name="UV Wrap",
        description="How texture wraps beyond UV bounds",
        items=uv_extension_items,
        default="REPEAT",
        update=update_uv_extension,
    )

    edge_detect_radius: FloatProperty(
        name="Edge Detect Radius",
        description="Edge detect radius",
        default=0.05,
        min=0.0,
        max=10.0,
        precision=3,
        update=update_layer_edge_detect_radius,
    )

    ao_distance: FloatProperty(
        name="Ambient Occlusion Distance",
        description="Ambient occlusion distance",
        default=1.0,
        min=0.0,
        max=10.0,
    )

    voronoi_feature: EnumProperty(
        name="Voronoi Feature",
        description="Voronoi feature for compute",
        items=voronoi_feature_items,
        default="F1",
        update=update_voronoi_feature,
    )

    use_temp_bake: BoolProperty(
        name="Use Temporary Bake",
        description="Use temporary bake to prevent cycles glitching",
        default=False,
    )

    original_type: EnumProperty(
        name="Original Layer Type",
        items=layer_type_items,
        default="IMAGE",
    )

    image_flip_y: BoolProperty(
        name="Image Flip G",
        description="Image Flip G (for DirectX normal maps)",
        default=False,
        update=update_image_flip_y,
    )

    divide_rgb_by_alpha: BoolProperty(
        name="Divide RGB by Alpha",
        description="Divide RGB by alpha to remove dark outlines",
        default=False,
        update=update_divide_rgb_by_alpha,
    )


# Register additional layer properties from separate module
from .layer_properties_layer import register_layer_properties

register_layer_properties(MLayer)


classes = (
    MLayerChannel,
    MLayer,
)


def _safe_register_class(cls):
    """Register class only if not already registered."""
    try:
        bpy.utils.register_class(cls)
    except ValueError as e:
        if "already registered" not in str(e):
            raise


def register():
    """Register layer property classes with Blender."""
    _safe_register_class(MNormalMapModifier)
    _safe_register_class(MLayerMaskChannel)
    _safe_register_class(MMaskModifier)
    _safe_register_class(MLayerMask)
    for cls in classes:
        _safe_register_class(cls)


def _safe_unregister_class(cls):
    """Unregister class only if it was registered."""
    try:
        bpy.utils.unregister_class(cls)
    except RuntimeError:
        pass  # Class was never registered


def unregister():
    """Unregister layer property classes from Blender."""
    for cls in reversed(classes):
        _safe_unregister_class(cls)
    _safe_unregister_class(MLayerMask)
    _safe_unregister_class(MMaskModifier)
    _safe_unregister_class(MLayerMaskChannel)
    _safe_unregister_class(MNormalMapModifier)
