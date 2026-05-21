# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transition bump influence and falloff operations."""

from ..layer.layer_utils import get_transition_bump_channel
from ..lib.lib import FALLOFF_CURVE, FALLOFF_CURVE_SMOOTH
from ..lib.lib_operations import check_if_node_is_duplicated_from_lib
from ..node.create_nodes import new_node
from ..node.node_utils import copy_node_props, remove_node
from ..subtree.get_subtree import get_tree
from .transition_ao import check_transition_ao_nodes
from .transition_ramp import check_transition_ramp_nodes


def save_transition_bump_falloff_cache(tree, ch):
    """
    Save transition bump falloff curve settings to a cache node.

    Parameters:
        tree: Node tree containing the falloff nodes.
        ch: Channel object to save falloff cache for.

    Returns:
        None. Cache node is created or updated directly in the tree.
    """
    tb_falloff = tree.nodes.get(ch.tb_falloff)

    # if (ch.transition_bump_falloff_type != 'CURVE' or not ch.transition_bump_falloff or
    #    not ch.enable_transition_bump or not ch.enable):

    if check_if_node_is_duplicated_from_lib(tb_falloff, FALLOFF_CURVE):
        cache = tree.nodes.get(ch.cache_falloff_curve)
        if not cache:
            cache = new_node(
                tree,
                ch,
                "cache_falloff_curve",
                "ShaderNodeRGBCurve",
                "Falloff Curve Cache",
            )
        curve_ref = tb_falloff.node_tree.nodes.get("_curve")
        copy_node_props(curve_ref, cache)
    elif check_if_node_is_duplicated_from_lib(tb_falloff, FALLOFF_CURVE_SMOOTH):
        cache = tree.nodes.get(ch.cache_falloff_curve)
        if not cache:
            cache = new_node(
                tree,
                ch,
                "cache_falloff_curve",
                "ShaderNodeRGBCurve",
                "Falloff Curve Cache",
            )
        ori = tb_falloff.node_tree.nodes.get("_original")
        curve_ref = ori.node_tree.nodes.get("_curve")
        copy_node_props(curve_ref, cache)


def remove_transition_bump_influence_nodes_to_other_channels(layer, tree):
    """
    Remove transition bump influence nodes from all channels in a layer.

    Parameters:
        layer: Layer object to remove influence nodes from.
        tree: Node tree containing the nodes to remove.

    Returns:
        None. Nodes are removed directly from the tree.
    """
    # Delete intensity multiplier from ramp
    for c in layer.channels:
        remove_node(tree, c, "intensity_multiplier")

        # Remove transition ao related nodes
        check_transition_ao_nodes(tree, layer, c)


def check_transition_bump_influences_to_other_channels(
    layer, tree=None, target_ch=None
):
    """
    Check and update transition bump influence nodes for all channels in a layer.

    Parameters:
        layer: Layer object to check influence nodes for.
        tree (optional): Node tree to check. If None, will be obtained from layer. Default: None.
        target_ch (optional): If provided, only check this specific channel. Default: None.

    Returns:
        None. Nodes are checked and updated directly in the tree.
    """

    mp = layer.id_data.mp

    if not tree:
        tree = get_tree(layer)

    # Trying to get bump channel
    bump_ch = get_transition_bump_channel(layer)

    # Add intensity multiplier to other channel mask
    for i, c in enumerate(layer.channels):

        # NOTE: Bump channel supposed to be already had a mask intensity multipler
        if c == bump_ch:
            continue

        # If target channel is set, its the only one will be processed
        if target_ch and target_ch != c:
            continue

        # Transition AO update
        check_transition_ao_nodes(tree, layer, c, bump_ch)

        # Transition Ramp update
        check_transition_ramp_nodes(tree, layer, c)
