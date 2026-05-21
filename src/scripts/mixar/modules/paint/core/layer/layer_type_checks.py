# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer type checking functions for maps and features.

This module provides functions to check what type of maps or features
a layer uses (bump maps, normal maps, vector displacement, etc.).
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...utils.common import get_channel_index
from ..layer.layer_utils import (
    get_height_channel,
    get_root_height_channel,
)
from ..subtree.get_subtree import get_list_of_direct_children
from .enable_state_checks import get_channel_enabled


def is_layer_using_bump_map(layer, root_ch=None):
    """Check if the layer is using a bump map for height/normal processing.

    Args:
        layer: The layer object to check.
        root_ch: The root height channel object. Default: None (will auto-detect).

    Returns:
        bool: True if the layer is using bump map, False otherwise.
    """
    mp = layer.id_data.mp
    if not root_ch:
        root_ch = get_root_height_channel(mp)
    if not root_ch:
        return False

    channel_idx = get_channel_index(root_ch)
    try:
        ch = layer.channels[channel_idx]
    except (IndexError, TypeError):
        return False
    if get_channel_enabled(ch, layer, root_ch):
        if layer.type == "GROUP":
            children = get_list_of_direct_children(layer)
            for child in children:
                if is_layer_using_bump_map(child):
                    return True
        elif ch.write_height and (
            ch.normal_map_type in {"BUMP_MAP", "BUMP_NORMAL_MAP"}
            or ch.enable_transition_bump
        ):
            return True

    return False


def is_layer_using_vdisp_map(layer, root_ch=None):
    """Check if the layer is using a vector displacement map.

    Args:
        layer: The layer object to check.
        root_ch: The root height channel object. Default: None (will auto-detect).

    Returns:
        bool: True if the layer is using vector displacement map, False otherwise.
    """
    mp = layer.id_data.mp
    if not root_ch:
        root_ch = get_root_height_channel(mp)
    if not root_ch:
        return False

    channel_idx = get_channel_index(root_ch)
    try:
        ch = layer.channels[channel_idx]
    except (IndexError, TypeError):
        return False
    if get_channel_enabled(ch, layer, root_ch):
        if layer.type == "GROUP":
            children = get_list_of_direct_children(layer)
            for child in children:
                if is_layer_using_vdisp_map(child):
                    return True
        elif ch.normal_map_type == "VECTOR_DISPLACEMENT_MAP":
            return True

    return False


def is_layer_using_normal_map(layer, root_ch=None):
    """Check if the layer is using a normal map.

    Args:
        layer: The layer object to check.
        root_ch: The root height channel object. Default: None (will auto-detect).

    Returns:
        bool: True if the layer is using normal map, False otherwise.
    """
    mp = layer.id_data.mp
    if not root_ch:
        root_ch = get_root_height_channel(mp)
    if not root_ch:
        return False

    channel_idx = get_channel_index(root_ch)
    try:
        ch = layer.channels[channel_idx]
    except (IndexError, TypeError):
        return False
    if get_channel_enabled(ch, layer, root_ch):
        if layer.type == "GROUP":
            children = get_list_of_direct_children(layer)
            for child in children:
                if is_layer_using_normal_map(child) or (
                    not ch.write_height and is_layer_using_bump_map(child)
                ):
                    return True
        elif not ch.write_height or ch.normal_map_type in {
            "NORMAL_MAP",
            "BUMP_NORMAL_MAP",
        }:
            return True

    return False


def is_layer_using_vector(layer, exclude_baked=False):
    """Check if the layer requires vector/UV coordinates for its operations.

    Args:
        layer: The layer object to check.
        exclude_baked: Whether to exclude baked layers from the check. Default: False.

    Returns:
        bool: True if the layer uses vector coordinates, False otherwise.
    """
    mp = layer.id_data.mp

    # Allow vector/mapping for COLOR (Fill) layers with 3D projections or Decal
    if layer.type == 'COLOR' and hasattr(layer, 'projection_type'):
        if layer.projection_type in {'TRIPLANAR', 'PLANAR', 'SPHERICAL', 'CYLINDRICAL', 'DECAL'}:
            return True

    if (not exclude_baked and layer.use_baked) or layer.type not in {
        "VCOL",
        "BACKGROUND",
        "COLOR",
        "GROUP",
        "HEMI",
        "OBJECT_INDEX",
        "BACKFACE",
        "EDGE_DETECT",
        "AO",
    }:
        return True

    for i, ch in enumerate(layer.channels):
        root_ch = mp.channels[i]
        if ch.enable:
            # New 4-option override system: IMAGE type needs mapping
            override_type = getattr(ch, 'override_type', 'LAYER')
            if override_type == "IMAGE":
                return True
            # Legacy override system (for backward compatibility)
            if ch.override and ch.override_type not in {"VCOL", "DEFAULT", "LAYER", "PASSTHROUGH", "OVERRIDE"}:
                return True
            # Normal channel's override_1 for normal map images
            if (
                root_ch.type == "NORMAL"
                and ch.normal_map_type in {"NORMAL_MAP", "BUMP_NORMAL_MAP"}
                and ch.override_1
                and ch.override_1_type == "IMAGE"
            ):
                return True

    for mask in layer.masks:
        if mask.enable and mask.texcoord_type == "Layer":
            return True

    return False


def is_layer_vdm(layer):
    """Check if the layer is a vector displacement map layer.

    Args:
        layer: The layer object to check.

    Returns:
        bool: True if the layer is a VDM layer, False otherwise.
    """
    hch = get_height_channel(layer)
    if not hch or not hch.enable or hch.normal_map_type != "VECTOR_DISPLACEMENT_MAP":
        return False

    return True


def get_first_vdm_layer(mp):
    """Get the first enabled vector displacement map layer in the material.

    Args:
        mp: The MPaint material data object.

    Returns:
        Layer object if a VDM layer is found, None otherwise.
    """
    for l in mp.layers:
        if not l.enable:
            continue
        if is_layer_vdm(l):
            return l

    return None


def any_decal_inside_layer(layer):
    """Check if the layer or any of its masks use decal texture coordinates.

    Args:
        layer: The layer object to check.

    Returns:
        bool: True if decal coordinates are used, False otherwise.
    """
    if layer.texcoord_type == "Decal":
        return True

    for mask in layer.masks:
        if mask.texcoord_type == "Decal":
            return True

    return False


def check_need_prev_normal(layer):
    """Check if the layer or its masks need the previous normal for processing.

    Args:
        layer: The layer object to check.

    Returns:
        bool: True if previous normal is needed, False otherwise.
    """
    mp = layer.id_data.mp
    height_root_ch = get_root_height_channel(mp)

    # Check if previous normal is needed
    need_prev_normal = False
    if (
        layer.type in {"HEMI", "EDGE_DETECT", "AO"}
        and layer.hemi_use_prev_normal
        and height_root_ch
    ):
        need_prev_normal = True

    # Also check mask
    if not need_prev_normal:
        for mask in layer.masks:
            if (
                mask.type in {"HEMI", "EDGE_DETECT", "AO"}
                and mask.hemi_use_prev_normal
                and height_root_ch
            ):
                need_prev_normal = True
                break

    return need_prev_normal
