# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transition ambient occlusion (AO) node operations."""

import re

from ...utils.constants import GAMMA
from ..layer.get_channels import get_channel_enabled
from ..lib.lib import (
    TRANSITION_AO,
    TRANSITION_AO_BG_MIX,
    TRANSITION_AO_FLIP,
    TRANSITION_AO_STRAIGHT_OVER,
)
from ..lib.lib_operations import duplicate_lib_node_tree
from ..node.node_utils import remove_node
from ..node.update_nodes import replace_new_node
from ..subtree.get_subtree import get_tree


def set_transition_ao_intensity_link(ch, tree=None, layer=None, tao=None):
    """
    Set the intensity link value for transition AO (ambient occlusion) nodes.

    Parameters:
        ch: Channel object containing transition AO settings.
        tree (optional): Node tree containing the AO node. Default: None.
        layer (optional): Layer containing the channel. Default: None.
        tao (optional): Transition AO node. If None, will be obtained from tree. Default: None.

    Returns:
        None. The AO node's intensity link is updated directly.
    """

    if not layer:
        m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", ch.path_from_id())
        if not m:
            return
        mp = ch.id_data.mp
        layer = mp.layers[int(m.group(1))]

    if not tree:
        tree = get_tree(layer)

    if tree and not tao:
        tao = tree.nodes.get(ch.tao)

    if tao:
        tao.inputs["Intensity Link"].default_value = (
            0.0 if ch.transition_ao_intensity_unlink else 1.0
        )


def check_transition_ao_nodes(tree, layer, ch, bump_ch=None):
    """
    Check and update transition ambient occlusion nodes for a channel.

    Parameters:
        tree: Node tree to check and update AO nodes in.
        layer: Layer object containing the channel.
        ch: Channel to check transition AO nodes for.
        bump_ch (optional): Bump channel reference. Default: None.

    Returns:
        None. Nodes are checked and updated directly in the tree.
    """

    mp = layer.id_data.mp

    # if (not bump_ch or not ch.enable_transition_ao) or (mp.disable_quick_toggle and not ch.enable):
    if (not bump_ch or not ch.enable_transition_ao) or not get_channel_enabled(ch):
        remove_node(tree, ch, "tao")

    elif bump_ch != ch and ch.enable_transition_ao:

        mp = ch.id_data.mp
        match = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", ch.path_from_id())
        root_ch = mp.channels[int(match.group(2))]

        # if layer.type == 'BACKGROUND' and ch.transition_ao_blend_type == 'MIX':
        if (
            layer.type == "BACKGROUND"
            and bump_ch.transition_bump_flip
            and ch.transition_ao_blend_type == "MIX"
        ):

            tao, dirty = replace_new_node(
                tree,
                ch,
                "tao",
                "ShaderNodeGroup",
                "Transition AO",
                TRANSITION_AO_BG_MIX,
                return_status=True,
            )
            if dirty:
                duplicate_lib_node_tree(tao)

        # elif layer.type == 'BACKGROUND' or bump_ch.transition_bump_flip:
        elif bump_ch.transition_bump_flip:

            tao, dirty = replace_new_node(
                tree,
                ch,
                "tao",
                "ShaderNodeGroup",
                "Transition AO",
                TRANSITION_AO_FLIP,
                return_status=True,
            )
            if dirty:
                duplicate_lib_node_tree(tao)

        elif ch.transition_ao_blend_type == "MIX" and (
            layer.parent_idx != -1 or (root_ch.type == "RGB" and root_ch.enable_alpha)
        ):
            tao = replace_new_node(
                tree,
                ch,
                "tao",
                "ShaderNodeGroup",
                "Transition AO",
                TRANSITION_AO_STRAIGHT_OVER,
            )

        else:
            tao, dirty = replace_new_node(
                tree,
                ch,
                "tao",
                "ShaderNodeGroup",
                "Transition AO",
                TRANSITION_AO,
                return_status=True,
            )
            if dirty:
                duplicate_lib_node_tree(tao)

        # Blend type
        ao_blend = tao.node_tree.nodes.get("_BLEND")
        if ao_blend and ao_blend.blend_type != ch.transition_ao_blend_type:
            ao_blend.blend_type = ch.transition_ao_blend_type

        set_transition_ao_intensity_link(ch, tree, layer, tao)

        if root_ch.colorspace == "SRGB":
            tao.inputs["Gamma"].default_value = 1.0 / GAMMA
        else:
            tao.inputs["Gamma"].default_value = 1.0
