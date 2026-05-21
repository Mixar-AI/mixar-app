# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Invoke logic for MBakeEntityToImage operator."""

import re

import bpy

from ....core.layer.layer_utils import get_uv_layers
from ....core.node.node_utils import get_active_mpaint_node
from ....core.subtree.get_subtree import get_mask_tree, get_source_tree
from ....utils.blender_commons import (
    get_active_object,
    get_unique_name,
    get_user_preferences,
)
from ....utils.common import get_addon_title
from ....utils.constants import TEMP_UV
from ...udim.udim_utils import get_udim_segment_tilenums


def invoke_bake_entity_to_image(operator, context, event):
    """Handle the invoke logic for MBakeEntityToImage operator.

    Args:
        operator: The MBakeEntityToImage operator instance
        context: Blender context
        event: Blender event

    Returns:
        Set containing either 'FINISHED' or dialog result
    """
    operator.invoke_operator(context)

    obj = get_active_object()
    mpup = get_user_preferences()
    node = get_active_mpaint_node()
    mp = node.node_tree.mp

    operator.entity = context.entity
    operator.layer = None
    operator.mask = None

    if not hasattr(context, "entity"):
        return operator.execute(context)

    # Check entity path and extract layer/mask information
    result = _parse_entity_path(operator, mp)
    if result is None:
        return operator.execute(context)

    # Get source tree and baked source node
    if operator.mask:
        source_tree = get_mask_tree(operator.mask)
    else:
        source_tree = get_source_tree(operator.layer)
    baked_source = source_tree.nodes.get(operator.entity.baked_source)

    overwrite_image = None
    if baked_source and baked_source.image:
        overwrite_image = baked_source.image

    # Set name based on overwrite image or generate new one
    _setup_name(operator, node, overwrite_image)

    # Setup UV map collection
    _setup_uv_map_collection(operator, obj)

    # Configure settings based on overwrite image or set defaults
    if overwrite_image:
        _configure_from_overwrite(operator, overwrite_image, mpup)
    else:
        _configure_defaults(operator)

    if get_user_preferences().skip_property_popups and not event.shift:
        return operator.execute(context)

    return context.window_manager.invoke_props_dialog(operator, width=320)


def _parse_entity_path(operator, mp):
    """Parse the entity path to determine if it's a layer or mask.

    Args:
        operator: The MBakeEntityToImage operator instance
        mp: MPaint property group

    Returns:
        True if valid entity found, None otherwise
    """
    m1 = re.match(r"^mp\.layers\[(\d+)\]$", operator.entity.path_from_id())
    m2 = re.match(
        r"^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$", operator.entity.path_from_id()
    )

    if m1:
        layer_idx = int(m1.group(1))
        if layer_idx >= len(mp.layers):
            return None
        operator.layer = mp.layers[layer_idx]
        operator.mask = None
        operator.index = layer_idx
        operator.entities = mp.layers

        # NOTE: Duplicate entity currently doesn't work on layer so make sure to disable it
        operator.duplicate_entity = False
        return True
    elif m2:
        layer_idx = int(m2.group(1))
        mask_idx = int(m2.group(2))
        if layer_idx >= len(mp.layers):
            return None
        operator.layer = mp.layers[layer_idx]
        if mask_idx >= len(operator.layer.masks):
            return None
        operator.mask = operator.layer.masks[mask_idx]
        operator.index = mask_idx
        operator.entities = operator.layer.masks
        return True

    return None


def _setup_name(operator, node, overwrite_image):
    """Set up the name for the baked image.

    Args:
        operator: The MBakeEntityToImage operator instance
        node: Active mpaint node
        overwrite_image: Image to overwrite or None
    """
    if (
        overwrite_image
        and not overwrite_image.yia.is_image_atlas
        and not overwrite_image.yua.is_udim_atlas
    ):
        operator.name = overwrite_image.name
    else:
        name = node.node_tree.name.replace(get_addon_title() + " ", "")
        operator.name = name + " " + operator.entity.name
        operator.name = get_unique_name(operator.name, bpy.data.images)


def _setup_uv_map_collection(operator, obj):
    """Set up the UV map collection.

    Args:
        operator: The MBakeEntityToImage operator instance
        obj: Active object
    """
    uv_layers = get_uv_layers(obj)

    operator.uv_map_coll.clear()
    for uv in uv_layers:
        if not uv.name.startswith(TEMP_UV):
            operator.uv_map_coll.add().name = uv.name


def _configure_from_overwrite(operator, overwrite_image, mpup):
    """Configure operator settings from an existing image.

    Args:
        operator: The MBakeEntityToImage operator instance
        overwrite_image: Image to overwrite
        mpup: User preferences
    """
    # Get segment set width and height
    segment = None
    if overwrite_image.yia.is_image_atlas:
        segment = overwrite_image.yia.segments.get(
            operator.entity.baked_segment_name
        )
        operator.width = segment.width
        operator.height = segment.height
    elif overwrite_image.yua.is_udim_atlas:
        segment = overwrite_image.yua.segments.get(
            operator.entity.baked_segment_name
        )
        tilenums = get_udim_segment_tilenums(segment)
        if len(tilenums) > 0:
            tile = overwrite_image.tiles.get(tilenums[0])
            operator.width = tile.size[0]
            operator.height = tile.size[1]
    else:
        operator.width = (
            overwrite_image.size[0]
            if overwrite_image.size[0] != 0
            else mpup.default_new_image_size
        )
        operator.height = (
            overwrite_image.size[1]
            if overwrite_image.size[1] != 0
            else mpup.default_new_image_size
        )

    # Get bake info
    bi = segment.bake_info if segment else overwrite_image.m_bake_info

    # Copy bake info attributes to operator
    _copy_bake_info_to_operator(operator, bi)

    # Set UV map
    if (
        operator.entity.baked_uv_name != ""
        and operator.entity.baked_uv_name in operator.uv_map_coll
    ):
        operator.uv_map = operator.entity.baked_uv_name
    elif operator.entity.uv_name in operator.uv_map_coll:
        operator.uv_map = operator.entity.uv_name


def _copy_bake_info_to_operator(operator, bi):
    """Copy bake info attributes to the operator.

    Args:
        operator: The MBakeEntityToImage operator instance
        bi: Bake info property group
    """
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


def _configure_defaults(operator):
    """Configure default operator settings for new bakes.

    Args:
        operator: The MBakeEntityToImage operator instance
    """
    if len(operator.uv_map_coll) > 0:
        operator.uv_map = operator.uv_map_coll[0].name

    if operator.entity.type in {"EDGE_DETECT", "HEMI", "AO"}:
        operator.fxaa = False
    else:
        operator.fxaa = True

    # Auto set some props for some types
    if operator.entity.type in {"EDGE_DETECT", "AO"}:
        operator.samples = 32
        operator.denoise = True
    else:
        operator.samples = 1
        operator.denoise = False
