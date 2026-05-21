# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transition ramp node operations."""

import re

from ...utils.constants import GAMMA
from ..layer.get_channels import get_channel_enabled
from ..layer.layer_utils import get_transition_bump_channel
from ..lib.lib import (
    RAMP,
    RAMP_BG_MIX,
    RAMP_BG_MIX_CHILD,
    RAMP_BG_MIX_UNLINK,
    RAMP_FLIP,
    RAMP_FLIP_BLEND,
    RAMP_FLIP_STRAIGHT_OVER_BLEND,
    RAMP_STRAIGHT_OVER,
)
from ..lib.lib_operations import duplicate_lib_node_tree
from ..node.create_nodes import new_node
from ..node.node_utils import copy_node_props, remove_node
from ..node.update_nodes import replace_new_node


def check_transition_ramp_nodes(tree, layer, ch):
    """
    Check and update transition ramp nodes for a channel.

    Parameters:
        tree: Node tree to check and update ramp nodes in.
        layer: Layer object containing the channel.
        ch: Channel to check transition ramp nodes for.

    Returns:
        None. Nodes are checked and updated directly in the tree.
    """

    mp = layer.id_data.mp
    # if mp.disable_quick_toggle and not ch.enable:
    if not get_channel_enabled(ch):
        remove_transition_ramp_nodes(tree, ch)
        return

    if ch.enable_transition_ramp:
        set_transition_ramp_nodes(tree, layer, ch)
    else:
        remove_transition_ramp_nodes(tree, ch)


def remove_transition_ramp_nodes(tree, ch):
    """
    Remove transition ramp nodes from a channel.

    Parameters:
        tree: Node tree containing the ramp nodes.
        ch: Channel object to remove ramp nodes from.

    Returns:
        None. Nodes are removed directly from the tree after saving to cache.
    """
    # Save ramp first
    save_ramp(tree, ch)

    remove_node(tree, ch, "tr_ramp")
    remove_node(tree, ch, "tr_ramp_blend")


def set_transition_ramp_nodes(tree, layer, ch):
    """
    Create or update transition ramp nodes for a channel.

    Parameters:
        tree: Node tree to add or update ramp nodes in.
        layer: Layer object containing the channel.
        ch: Channel to set transition ramp nodes for.

    Returns:
        None. Nodes are created or updated directly in the tree.
    """

    mp = ch.id_data.mp
    match = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", ch.path_from_id())
    root_ch = mp.channels[int(match.group(2))]

    bump_ch = get_transition_bump_channel(layer)

    # Save previous ramp to cache
    save_ramp(tree, ch)

    # if bump_ch and (bump_ch.transition_bump_flip or layer.type == 'BACKGROUND'):
    if bump_ch and bump_ch.transition_bump_flip:

        tr_ramp, dirty = replace_new_node(
            tree,
            ch,
            "tr_ramp",
            "ShaderNodeGroup",
            "Transition Ramp",
            RAMP_FLIP,
            return_status=True,
        )
        if dirty:
            duplicate_lib_node_tree(tr_ramp)

        if ch.transition_ramp_blend_type == "MIX" and (
            (root_ch.type == "RGB" and root_ch.enable_alpha) or layer.parent_idx != -1
        ):
            tr_ramp_blend = replace_new_node(
                tree,
                ch,
                "tr_ramp_blend",
                "ShaderNodeGroup",
                "Transition Ramp Blend",
                RAMP_FLIP_STRAIGHT_OVER_BLEND,
                hard_replace=True,
            )
        else:
            tr_ramp_blend, dirty = replace_new_node(
                tree,
                ch,
                "tr_ramp_blend",
                "ShaderNodeGroup",
                "Transition Ramp Blend",
                RAMP_FLIP_BLEND,
                return_status=True,
                hard_replace=True,
            )
            if dirty:
                duplicate_lib_node_tree(tr_ramp_blend)

            # Get blend node
            ramp_blend = tr_ramp_blend.node_tree.nodes.get("_BLEND")
            ramp_blend.blend_type = ch.transition_ramp_blend_type

    else:
        if layer.type == "BACKGROUND" and ch.transition_ramp_blend_type == "MIX":
            if ch.transition_ramp_intensity_unlink:
                tr_ramp, dirty = replace_new_node(
                    tree,
                    ch,
                    "tr_ramp",
                    "ShaderNodeGroup",
                    "Transition Ramp",
                    RAMP_BG_MIX_UNLINK,
                    return_status=True,
                )
            elif layer.parent_idx != -1:
                tr_ramp, dirty = replace_new_node(
                    tree,
                    ch,
                    "tr_ramp",
                    "ShaderNodeGroup",
                    "Transition Ramp",
                    RAMP_BG_MIX_CHILD,
                    return_status=True,
                )
            else:
                tr_ramp, dirty = replace_new_node(
                    tree,
                    ch,
                    "tr_ramp",
                    "ShaderNodeGroup",
                    "Transition Ramp",
                    RAMP_BG_MIX,
                    return_status=True,
                )
        elif (
            ch.transition_ramp_intensity_unlink
            and ch.transition_ramp_blend_type == "MIX"
        ):
            tr_ramp, dirty = replace_new_node(
                tree,
                ch,
                "tr_ramp",
                "ShaderNodeGroup",
                "Transition Ramp",
                RAMP_STRAIGHT_OVER,
                return_status=True,
            )
        else:
            tr_ramp, dirty = replace_new_node(
                tree,
                ch,
                "tr_ramp",
                "ShaderNodeGroup",
                "Transition Ramp",
                RAMP,
                return_status=True,
            )

        if dirty:
            duplicate_lib_node_tree(tr_ramp)

        # Get blend node
        ramp_blend = tr_ramp.node_tree.nodes.get("_BLEND")
        if ramp_blend:
            ramp_blend.blend_type = ch.transition_ramp_blend_type

        remove_node(tree, ch, "tr_ramp_blend")

    # Set ramp blend intensity link
    tr_ramp_blend = tree.nodes.get(ch.tr_ramp_blend)
    if tr_ramp_blend:
        tr_ramp_blend.inputs["Intensity Link"].default_value = (
            0.0 if ch.transition_ramp_intensity_unlink else 1.0
        )

    # Load ramp from cache
    load_ramp(tree, ch)

    if root_ch.colorspace == "SRGB":
        tr_ramp.inputs["Gamma"].default_value = 1.0 / GAMMA
    else:
        tr_ramp.inputs["Gamma"].default_value = 1.0


def load_ramp(tree, ch):
    """
    Load ramp settings from cache to the active ramp node.

    Parameters:
        tree: Node tree containing the ramp nodes.
        ch: Channel object to load ramp settings for.

    Returns:
        None. Ramp properties are copied from cache node to active ramp node.
    """
    tr_ramp = tree.nodes.get(ch.tr_ramp)
    if not tr_ramp:
        return

    ramp = tr_ramp.node_tree.nodes.get("_RAMP")

    cache_ramp = tree.nodes.get(ch.cache_ramp)
    if cache_ramp:
        copy_node_props(cache_ramp, ramp)


def save_ramp(tree, ch):
    """
    Save ramp settings from the active ramp node to cache.

    Parameters:
        tree: Node tree containing the ramp nodes.
        ch: Channel object to save ramp settings for.

    Returns:
        None. Ramp properties are copied to cache node.
    """
    tr_ramp = tree.nodes.get(ch.tr_ramp)
    if not tr_ramp or tr_ramp.type != "GROUP":
        return

    ramp = tr_ramp.node_tree.nodes.get("_RAMP")
    cache_ramp = tree.nodes.get(ch.cache_ramp)

    if not cache_ramp:
        cache_ramp = new_node(tree, ch, "cache_ramp", "ShaderNodeValToRGB")

    copy_node_props(ramp, cache_ramp)
