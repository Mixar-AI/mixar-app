# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel checking and processing requirement functions.

This module provides functions to check channel properties, aggregate layer
channel usage, and determine processing requirements.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...utils.common import get_channel_index, set_mix_clamp
from ...utils.constants import io_suffix
from ..layer.layer_utils import (
    get_height_channel,
    get_layer_index,
    get_root_height_channel,
)
from ..node.create_nodes import check_new_mix_node
from ..node.node_utils import (
    is_normal_height_input_connected,
    is_normal_input_connected,
    is_normal_vdisp_input_connected,
    remove_node,
)
from ..subtree.get_subtree import get_source_tree
from .enable_state_checks import get_channel_enabled
from .layer_type_checks import (
    get_first_vdm_layer,
    is_layer_using_bump_map,
    is_layer_using_normal_map,
    is_layer_using_vdisp_map,
)


def has_previous_layer_channels(layer, root_ch):
    """Check if there are previous layer channels enabled for the given root channel.

    Args:
        layer: The layer object to check.
        root_ch: The root channel object to check against.

    Returns:
        bool: True if previous layers have this channel enabled, False otherwise.
    """
    mp = layer.id_data.mp

    if layer.parent_idx == -1:
        return True

    ch_idx = get_channel_index(root_ch)
    layer_idx = get_layer_index(layer)

    for i, t in reversed(list(enumerate(mp.layers))):
        if i > layer_idx and layer.parent_idx == t.parent_idx:
            for j, c in enumerate(t.channels):
                if ch_idx == j and get_channel_enabled(c, t, mp.channels[ch_idx]):
                    return True

    return False


def any_layers_using_bump_map(root_ch):
    """Check if any layers in the material are using bump maps.

    Args:
        root_ch: The root channel object to check.

    Returns:
        bool: True if any layer is using bump map, False otherwise.
    """
    if root_ch.type != "NORMAL":
        return False
    mp = root_ch.id_data.mp

    for layer in mp.layers:
        if is_layer_using_bump_map(layer, root_ch):
            return True

    return False


def any_layers_using_displacement(root_ch):
    """Check if any layers are using displacement (bump maps or vector displacement).

    Args:
        root_ch: The root channel object to check.

    Returns:
        bool: True if any layer is using displacement, False otherwise.
    """
    if any_layers_using_bump_map(root_ch):
        return True

    mp = root_ch.id_data.mp
    vdm_layer = get_first_vdm_layer(mp)
    if vdm_layer:
        return True

    return False


def any_layers_using_normal_map(root_ch):
    """Check if any layers in the material are using normal maps.

    Args:
        root_ch: The root channel object to check.

    Returns:
        bool: True if any layer is using normal map, False otherwise.
    """
    if root_ch.type != "NORMAL":
        return False
    mp = root_ch.id_data.mp

    for layer in mp.layers:
        if is_layer_using_normal_map(layer, root_ch):
            return True

    return False


def any_layers_using_channel(root_ch):
    """Check if any layers are using the specified root channel.

    Args:
        root_ch: The root channel object to check.

    Returns:
        bool: True if any layer has this channel enabled, False otherwise.
    """
    mp = root_ch.id_data.mp
    channel_idx = get_channel_index(root_ch)

    for layer in mp.layers:
        try:
            ch = layer.channels[channel_idx]
        except (IndexError, TypeError):
            continue
        if get_channel_enabled(ch, layer, root_ch):
            return True

    return False


def is_any_layer_using_channel(root_ch, node=None):
    """Check if any non-group/background layer is using the specified channel.

    Args:
        root_ch: The root channel object to check.
        node: Optional node to check for input connections. Default: None.

    Returns:
        bool: True if any non-group/background layer is using this channel, False otherwise.
    """
    mp = root_ch.id_data.mp
    ch_idx = get_channel_index(root_ch)

    # Check node inputs
    if node:
        inp = node.inputs.get(root_ch.name)
        if inp and len(inp.links):
            return True
        inp = node.inputs.get(root_ch.name + io_suffix["ALPHA"])
        if inp and len(inp.links):
            return True
        if root_ch.type == "NORMAL":
            inp = node.inputs.get(root_ch.name + io_suffix["HEIGHT"])
            if inp and len(inp.links):
                return True
            inp = node.inputs.get(root_ch.name + io_suffix["VDISP"])
            if inp and len(inp.links):
                return True

    for layer in mp.layers:
        if layer.type in {"GROUP", "BACKGROUND"}:
            continue
        if get_channel_enabled(layer.channels[ch_idx], layer):
            return True

    return False


def any_layers_using_vdisp(root_ch):
    """Check if any layers are using vector displacement.

    Args:
        root_ch: The root channel object to check.

    Returns:
        bool: True if any layer is using vector displacement, False otherwise.
    """
    mp = root_ch.id_data.mp
    channel_index = get_channel_index(root_ch)

    if is_normal_vdisp_input_connected(root_ch):
        return True

    for l in mp.layers:
        if l.type in {"GROUP", "BACKGROUND"}:
            continue
        if channel_index >= len(l.channels):
            continue
        c = l.channels[channel_index]
        if not get_channel_enabled(c, l):
            continue
        if c.normal_map_type == "VECTOR_DISPLACEMENT_MAP":
            return True

    return False


def any_layers_using_disp(root_ch):
    """Check if any layers are using displacement (height-based).

    Args:
        root_ch: The root channel object to check.

    Returns:
        bool: True if any layer is using displacement, False otherwise.
    """
    mp = root_ch.id_data.mp
    channel_index = get_channel_index(root_ch)

    if is_normal_height_input_connected(root_ch):
        return True

    for l in mp.layers:
        if l.type in {"GROUP", "BACKGROUND"}:
            continue
        if channel_index >= len(l.channels):
            continue
        c = l.channels[channel_index]
        if not get_channel_enabled(c, l):
            continue
        if c.normal_map_type in {"BUMP_MAP", "BUMP_NORMAL_MAP"} and c.write_height:
            return True

    return False


def is_root_ch_prop_node_unique(root_ch, prop):
    """Check if a property value on the root channel is unique among all channels.

    Args:
        root_ch: The root channel object to check.
        prop: The property name to check for uniqueness.

    Returns:
        bool: True if the property value is unique, False otherwise.
    """
    mp = root_ch.id_data.mp

    for ch in mp.channels:
        try:
            if ch != root_ch and getattr(ch, prop) == getattr(root_ch, prop):
                return False
        except Exception as e:
            logger.error("Error checking root channel property uniqueness: %s", e)

    return True


def is_height_process_needed(layer):
    """Check if height/bump processing is needed for this layer.

    Args:
        layer: The layer object to check.

    Returns:
        bool: True if height processing is needed, False otherwise.
    """
    mp = layer.id_data.mp
    height_root_ch = get_root_height_channel(mp)
    if not height_root_ch:
        return False

    height_ch = get_height_channel(layer)
    if not height_ch or not height_ch.enable:
        return False

    if mp.layer_preview_mode and height_ch.normal_map_type != "VECTOR_DISPLACEMENT_MAP":
        return True

    if layer.type == "GROUP":
        if is_layer_using_bump_map(layer, height_root_ch):
            return True
    elif (
        height_ch.normal_map_type in {"BUMP_MAP", "BUMP_NORMAL_MAP"}
        or height_ch.enable_transition_bump
    ):
        return True

    return False


def is_vdisp_process_needed(layer):
    """Check if vector displacement processing is needed for this layer.

    Args:
        layer: The layer object to check.

    Returns:
        bool: True if vector displacement processing is needed, False otherwise.
    """
    mp = layer.id_data.mp
    height_root_ch = get_root_height_channel(mp)
    if not height_root_ch:
        return False

    height_ch = get_height_channel(layer)
    if not height_ch or not height_ch.enable:
        return False

    if layer.type == "GROUP":
        if is_layer_using_vdisp_map(layer, height_root_ch):
            return True
    elif height_ch.normal_map_type == "VECTOR_DISPLACEMENT_MAP":
        return True

    return False


def is_normal_process_needed(layer):
    """Check if normal map processing is needed for this layer.

    Args:
        layer: The layer object to check.

    Returns:
        bool: True if normal processing is needed, False otherwise.
    """
    mp = layer.id_data.mp
    height_root_ch = get_root_height_channel(mp)
    if not height_root_ch:
        return False

    height_ch = get_height_channel(layer)
    if not height_ch or not height_ch.enable:
        return False

    if mp.layer_preview_mode and height_ch.normal_map_type != "VECTOR_DISPLACEMENT_MAP":
        return True

    if layer.type == "GROUP":
        if (
            is_layer_using_bump_map(layer, height_root_ch)
            and not height_ch.write_height
        ):
            return True
    elif (
        height_ch.normal_map_type in {"NORMAL_MAP", "BUMP_MAP", "BUMP_NORMAL_MAP"}
        or not height_ch.write_height
    ):
        return True

    return False


def is_overlay_normal_empty(root_ch):
    """Check if the overlay normal channel has no active normal maps.

    Args:
        root_ch: The root channel object to check.

    Returns:
        bool: True if no normal maps are active, False otherwise.
    """
    mp = root_ch.id_data.mp
    channel_index = get_channel_index(root_ch)

    if is_normal_input_connected(root_ch):
        return False

    for l in mp.layers:
        if l.type in {"GROUP", "BACKGROUND"}:
            continue
        if channel_index >= len(l.channels):
            continue
        c = l.channels[channel_index]
        if not get_channel_enabled(c, l):
            continue
        if c.normal_map_type == "NORMAL_MAP" or (
            c.normal_map_type == "BUMP_MAP" and not c.write_height
        ):
            return False

    return True


def check_layer_divider_alpha(layer, tree=None):
    """Check and setup the divider alpha node for the layer if needed.

    This handles the "divide RGB by alpha" operation for IMAGE and VCOL layers
    to fix spread issues.

    Args:
        layer: The layer object to check.
        tree: The node tree to work with. Default: None (will auto-detect from layer).

    Returns:
        None
    """
    if not tree:
        tree = get_source_tree(layer)

    if layer.divide_rgb_by_alpha and layer.type in {"IMAGE", "VCOL"}:
        divider_alpha = check_new_mix_node(tree, layer, "divider_alpha", "Spread Fix")
        divider_alpha.blend_type = "DIVIDE"
        divider_alpha.inputs[0].default_value = 1.0
        set_mix_clamp(divider_alpha, True)
    else:
        remove_node(tree, layer, "divider_alpha")
