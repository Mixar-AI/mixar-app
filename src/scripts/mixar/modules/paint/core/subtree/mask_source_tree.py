# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask source tree operations for texture painting.

This module contains functions for checking and updating mask source trees,
including UV neighbor node management for masks.
"""

import re

from ..element.update_uv import set_uv_neighbor_resolution
from ..layer.check_layers import (
    get_channel_enabled,
    get_mask_enabled,
    is_height_process_needed,
)
from ..layer.get_channels import get_bump_chain, get_write_height_normal_channel
from ..layer.layer_utils import get_layer_channel_index, get_smooth_bump_channel
from ..lib.lib_operations import get_neighbor_uv_tree_name
from ..node.create_nodes import replace_new_node
from ..node.node_utils import remove_node
from ..subtree.update_subtree import (
    disable_mask_source_tree,
    enable_mask_source_tree,
)
from .get_subtree import get_tree


def check_mask_source_tree(layer, specific_mask=None):  # , ch=None):
    """Check and update mask source tree states for all masks in a layer.

    Evaluates whether each mask should have its source tree enabled or disabled
    based on smooth bump channel settings, mask state, and height processing requirements.

    Args:
        layer: The layer object containing masks to check.
        specific_mask (optional): If provided, only checks this specific mask.
            Defaults to None, which checks all masks in the layer.

    Returns:
        None
    """
    # print("Checking mask source tree. Layer: " + layer.name + ' Specific Mask: ' + str(specific_mask))

    mp = layer.id_data.mp

    smooth_bump_ch = get_smooth_bump_channel(layer)
    write_height_ch = get_write_height_normal_channel(layer)
    chain = get_bump_chain(layer)
    ch_idx = get_layer_channel_index(layer, smooth_bump_ch)
    tree = get_tree(layer)

    height_process_needed = is_height_process_needed(layer)

    for i, mask in enumerate(layer.masks):
        if specific_mask and specific_mask != mask:
            continue

        if (
            smooth_bump_ch
            and get_channel_enabled(smooth_bump_ch, layer, mp.channels[ch_idx])
            and get_mask_enabled(mask)
            and (
                mask.channels[ch_idx].enable
                and height_process_needed
                and (write_height_ch or i < chain)
                and (
                    mask.use_baked
                    or mask.type
                    not in {
                        "VCOL",
                        "HEMI",
                        "OBJECT_INDEX",
                        "COLOR_ID",
                        "BACKFACE",
                        "EDGE_DETECT",
                    }
                )
            )
        ):
            enable_mask_source_tree(layer, mask)
        else:
            disable_mask_source_tree(layer, mask)

        check_mask_uv_neighbor(tree, layer, mask)


def check_mask_uv_neighbor(tree, layer, mask, mask_idx=-1):
    """Check and create/remove UV neighbor nodes for a mask based on requirements.

    Determines if UV neighbor nodes are needed for smooth bump processing and
    creates or removes them accordingly. Sets the appropriate resolution for
    neighbor UV calculations.

    Args:
        tree: The node tree to operate on.
        layer: The layer object containing the mask.
        mask: The mask object to check UV neighbor for.
        mask_idx (int, optional): Index of the mask in the layer's mask list.
            If -1, derives the index from the mask's path. Defaults to -1.

    Returns:
        bool: True if the tree was modified (node added or removed), False otherwise.
    """
    mp = layer.id_data.mp

    # Check if smooth bump channel is available
    smooth_bump_ch = get_smooth_bump_channel(layer)

    # Get channel that write height
    write_height_ch = get_write_height_normal_channel(layer)

    # Get mask index
    if mask_idx == -1:
        match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", mask.path_from_id())
        mask_idx = int(match.group(2))

    # Get chain
    chain = get_bump_chain(layer)

    if (
        smooth_bump_ch
        and get_channel_enabled(smooth_bump_ch)
        and get_mask_enabled(mask)
        and (
            (write_height_ch or mask_idx < chain)
            and (
                mask.use_baked
                or (
                    mask.type
                    not in {
                        "OBJECT_INDEX",
                        "COLOR_ID",
                        "BACKFACE",
                        "MODIFIER",
                        "EDGE_DETECT",
                        "HEMI",
                        "VCOL",
                    }
                    and mask.texcoord_type != "Layer"
                )
            )
        )
    ):

        # if not mask.use_baked and mask.type in {'VCOL', 'HEMI', 'EDGE_DETECT'}:
        #    lib_name = lib.NEIGHBOR_FAKE
        # else:
        lib_name = get_neighbor_uv_tree_name(mask.texcoord_type, entity=mask)

        uv_neighbor, dirty = replace_new_node(
            tree,
            mask,
            "uv_neighbor",
            "ShaderNodeGroup",
            "UV Neighbor",
            lib_name,
            return_status=True,
            hard_replace=True,
        )

        set_uv_neighbor_resolution(mask, uv_neighbor)

        return dirty

    else:
        return remove_node(tree, mask, "uv_neighbor")

    return False
