# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Invoke logic for MBakeToLayer operator."""

import bpy

from ....core.layer.layer_utils import get_root_height_channel, get_uv_layers
from ....core.node.get_nodes import get_layer_source, get_mask_source
from ....core.node.node_utils import get_active_mpaint_node
from ....utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_scene_objects,
    get_unique_name,
    get_user_preferences,
)
from ....utils.common import get_active_layer_safe, get_channel_index
from ....utils.constants import TEMP_UV, bake_type_suffixes
from ...udim.udim_utils import get_udim_segment_tilenums


def invoke_bake_to_layer(operator, context, event):
    """Handle the invoke logic for MBakeToLayer operator.

    Args:
        operator: The MBakeToLayer operator instance
        context: Blender context
        event: Blender event

    Returns:
        Set containing either 'FINISHED' or dialog result
    """
    operator.invoke_operator(context)

    if hasattr(context, "entity"):
        operator.entity = context.entity
    else:
        operator.entity = None

    obj = operator.obj = get_active_object()
    scene = operator.scene = context.scene
    node = get_active_mpaint_node()
    mp = node.node_tree.mp
    mpup = get_user_preferences()

    # Default normal map type is bump
    operator.normal_map_type = "BUMP_MAP"

    # Default samples is 1
    operator.samples = 1

    # Set channel to first one, just in case
    if len(mp.channels) > 0:
        operator.channel_idx = str(0)

    # Get height channel
    height_root_ch = get_root_height_channel(mp)

    # Set default float image
    if operator.type in {"POINTINESS", "MULTIRES_DISPLACEMENT"}:
        operator.hdr = True
    else:
        operator.hdr = False

    # Set name and configure type-specific defaults
    mat = get_active_material()
    _configure_type_defaults(operator, mp, height_root_ch)

    suffix = bake_type_suffixes[operator.type]
    operator.name = get_unique_name(mat.name + " " + suffix, bpy.data.images)

    operator.overwrite_choice = False
    operator.overwrite_name = ""
    overwrite_entity = None

    if operator.overwrite_current:
        overwrite_entity = operator.entity
    elif not operator.type.startswith("OTHER_OBJECT_") and operator.type not in {
        "SELECTED_VERTICES"
    }:
        overwrite_entity = _setup_overwrite_collection(operator, mp)

    _setup_overwrite_entity(operator, overwrite_entity, mpup)

    # Use active uv layer name by default
    uv_layers = get_uv_layers(obj)

    # UV Map collections update
    operator.uv_map_coll.clear()
    for uv in uv_layers:
        if not uv.name.startswith(TEMP_UV):
            operator.uv_map_coll.add().name = uv.name

    if len(operator.uv_map_coll) > 0 and not overwrite_entity:
        operator.uv_map = operator.uv_map_coll[0].name

    if len(operator.uv_map_coll) > 1:
        operator.uv_map_1 = operator.uv_map_coll[1].name

    # Cage object collections update
    operator.cage_object_coll.clear()
    for ob in get_scene_objects():
        if (
            ob != obj
            and ob not in bpy.context.selected_objects
            and ob.type == "MESH"
        ):
            operator.cage_object_coll.add().name = ob.name

    requires_popup = operator.type in {
        "OTHER_OBJECT_NORMAL",
        "OTHER_OBJECT_EMISSION",
        "OTHER_OBJECT_CHANNELS",
        "FLOW",
    }
    if (
        not requires_popup
        and get_user_preferences().skip_property_popups
        and not event.shift
    ):
        return operator.execute(context)

    return context.window_manager.invoke_props_dialog(operator, width=320)


def _configure_type_defaults(operator, mp, height_root_ch):
    """Configure type-specific default values.

    Args:
        operator: The MBakeToLayer operator instance
        mp: MPaint property group
        height_root_ch: Height root channel or None
    """
    if operator.type == "AO":
        operator.blend_type = "MULTIPLY"
        operator.samples = 32

        # Check Ambient occlusion channel if available
        for i, c in enumerate(mp.channels):
            if c.name in {"Ambient Occlusion", "AO"}:
                operator.channel_idx = str(i)
                break

    elif operator.type == "POINTINESS":
        operator.blend_type = "ADD"
        operator.fxaa = False

    elif operator.type == "CAVITY":
        operator.blend_type = "ADD"

    elif operator.type == "DUST":
        operator.blend_type = "MIX"

    elif operator.type == "PAINT_BASE":
        operator.blend_type = "MIX"

    elif operator.type == "BEVEL_NORMAL":
        operator.blend_type = "MIX"
        operator.normal_blend_type = "OVERLAY"
        operator.use_baked_disp = False
        operator.samples = 32

        if height_root_ch:
            operator.channel_idx = str(get_channel_index(height_root_ch))
            operator.normal_map_type = "NORMAL_MAP"

    elif operator.type == "BEVEL_MASK":
        operator.blend_type = "MIX"
        operator.use_baked_disp = False
        operator.samples = 32

    elif operator.type == "MULTIRES_NORMAL":
        operator.blend_type = "MIX"

        if height_root_ch:
            operator.channel_idx = str(get_channel_index(height_root_ch))
            operator.normal_map_type = "NORMAL_MAP"
            operator.normal_blend_type = "OVERLAY"

    elif operator.type == "MULTIRES_DISPLACEMENT":
        operator.blend_type = "MIX"

        if height_root_ch:
            operator.channel_idx = str(get_channel_index(height_root_ch))
            operator.normal_map_type = "BUMP_MAP"
            operator.normal_blend_type = "OVERLAY"

    elif operator.type == "OTHER_OBJECT_EMISSION":
        operator.blend_type = "MIX"
        operator.subsurf_influence = False
        operator.margin = 0

    elif operator.type in {"OTHER_OBJECT_NORMAL", "OBJECT_SPACE_NORMAL"}:
        operator.subsurf_influence = False

        if height_root_ch:
            operator.channel_idx = str(get_channel_index(height_root_ch))
            operator.normal_map_type = "NORMAL_MAP"
            operator.normal_blend_type = "OVERLAY"

        if operator.type == "OTHER_OBJECT_NORMAL":
            operator.margin = 0

    elif operator.type == "OTHER_OBJECT_CHANNELS":
        operator.blend_type = "MIX"
        operator.subsurf_influence = False
        operator.use_image_atlas = False
        operator.margin = 0

    elif operator.type == "SELECTED_VERTICES":
        operator.subsurf_influence = False
        operator.use_baked_disp = False

    elif operator.type == "FLOW":
        operator.blend_type = "MIX"

        # Check flow channel if available
        for i, c in enumerate(mp.channels):
            if "flow" in c.name.lower():
                operator.channel_idx = str(i)
                break


def _setup_overwrite_collection(operator, mp):
    """Set up the overwrite collection for layers/masks.

    Args:
        operator: The MBakeToLayer operator instance
        mp: MPaint property group

    Returns:
        Overwrite entity or None
    """
    # Clear overwrite_coll
    operator.overwrite_coll.clear()

    # Get overwritable layers
    if operator.target_type == "LAYER":
        for layer in mp.layers:
            if layer.type == "IMAGE":
                source = get_layer_source(layer)
                if source.image:
                    img = source.image
                    if (
                        img.m_bake_info.is_baked
                        and not img.m_bake_info.is_baked_channel
                        and img.m_bake_info.bake_type == operator.type
                    ):
                        operator.overwrite_coll.add().name = layer.name
                    elif img.yia.is_image_atlas or img.yua.is_udim_atlas:
                        if img.yia.is_image_atlas:
                            segment = img.yia.segments.get(layer.segment_name)
                        else:
                            segment = img.yua.segments.get(layer.segment_name)
                        if (
                            segment
                            and segment.bake_info.is_baked
                            and segment.bake_info.bake_type == operator.type
                        ):
                            operator.overwrite_coll.add().name = layer.name

    # Get overwritable masks
    elif len(mp.layers) > 0:
        active_layer = get_active_layer_safe(mp)
        if not active_layer:
            active_layer = mp.layers[0] if mp.layers else None
        if active_layer:
            for mask in active_layer.masks:
                if mask.type == "IMAGE":
                    source = get_mask_source(mask)
                    if source.image:
                        img = source.image
                        if (
                            img.m_bake_info.is_baked
                            and not img.m_bake_info.is_baked_channel
                            and img.m_bake_info.bake_type == operator.type
                        ):
                            operator.overwrite_coll.add().name = mask.name
                        elif img.yia.is_image_atlas or img.yua.is_udim_atlas:
                            if img.yia.is_image_atlas:
                                segment = img.yia.segments.get(mask.segment_name)
                            else:
                                segment = img.yua.segments.get(mask.segment_name)
                            if (
                                segment
                                and segment.bake_info.is_baked
                                and segment.bake_info.bake_type == operator.type
                            ):
                                operator.overwrite_coll.add().name = mask.name

    if len(operator.overwrite_coll) > 0:
        operator.overwrite_choice = True
        if operator.target_type == "LAYER":
            return mp.layers.get(operator.overwrite_coll[0].name)
        else:
            active_layer = get_active_layer_safe(mp)
            if active_layer:
                return active_layer.masks.get(operator.overwrite_coll[0].name)
    else:
        operator.overwrite_choice = False

    return None


def _setup_overwrite_entity(operator, overwrite_entity, mpup):
    """Set up overwrite entity properties.

    Args:
        operator: The MBakeToLayer operator instance
        overwrite_entity: The entity to overwrite or None
        mpup: User preferences
    """
    operator.overwrite_image_name = ""
    operator.overwrite_segment_name = ""

    if not overwrite_entity:
        return

    if operator.target_type == "LAYER":
        source = get_layer_source(overwrite_entity)
    else:
        source = get_mask_source(overwrite_entity)

    bi = None
    if overwrite_entity.type == "IMAGE" and source.image:
        operator.overwrite_image_name = source.image.name
        if (
            not source.image.yia.is_image_atlas
            and not source.image.yua.is_udim_atlas
        ):
            operator.overwrite_name = source.image.name
            operator.width = (
                source.image.size[0]
                if source.image.size[0] != 0
                else int(mpup.default_image_resolution)
            )
            operator.height = (
                source.image.size[1]
                if source.image.size[1] != 0
                else int(mpup.default_image_resolution)
            )
            operator.use_image_atlas = False
            bi = source.image.m_bake_info
        else:
            operator.overwrite_name = overwrite_entity.name
            operator.overwrite_segment_name = overwrite_entity.segment_name
            if source.image.yia.is_image_atlas:
                segment = source.image.yia.segments.get(
                    overwrite_entity.segment_name
                )
                operator.width = segment.width
                operator.height = segment.height
            else:
                segment = source.image.yua.segments.get(
                    overwrite_entity.segment_name
                )
                tilenums = get_udim_segment_tilenums(segment)
                if len(tilenums) > 0:
                    tile = source.image.tiles.get(tilenums[0])
                    operator.width = tile.size[0]
                    operator.height = tile.size[1]
            bi = segment.bake_info
            operator.use_image_atlas = True
        operator.hdr = source.image.is_float

    # Fill settings using bake info stored on image
    if bi:
        for attr in dir(bi):
            if attr in {"other_objects", "selected_objects"}:
                continue
            if attr.startswith("__"):
                continue
            if attr.startswith("bl_"):
                continue
            if attr in {"rna_type"}:
                continue
            try:
                setattr(operator, attr, getattr(bi, attr))
            except:
                pass

    operator.uv_map = overwrite_entity.uv_name
