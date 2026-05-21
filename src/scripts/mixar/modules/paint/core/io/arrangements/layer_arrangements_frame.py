# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer frame node arrangement functions.

This module handles the organization of layer nodes into visual frames
for better organization in the node tree.
"""

from ...element.frame_utils import (
    check_set_node_parent,
    clean_unused_frames,
    get_frame,
)
from ...subtree.get_subtree import get_tree


def rearrange_layer_frame_nodes(layer, tree=None):
    """Organize layer nodes into labeled frames for better visual organization.

    Groups related nodes (blend, mask, channel) into frames within the node tree
    for improved visual organization and navigation.

    Args:
        layer: The layer object containing channels and masks to organize.
        tree (optional): The node tree to organize. If None, retrieves tree from layer.
            Defaults to None.

    Returns:
        None
    """
    mp = layer.id_data.mp
    if not tree:
        tree = get_tree(layer)

    # Layer channels
    for i, ch in enumerate(layer.channels):
        root_ch = mp.channels[i]

        # Blend
        frame = get_frame(tree, '__blend__', str(i), root_ch.name + ' Blend')
        check_set_node_parent(tree, ch.decal_alpha, frame)
        check_set_node_parent(tree, ch.decal_alpha_n, frame)
        check_set_node_parent(tree, ch.decal_alpha_s, frame)
        check_set_node_parent(tree, ch.decal_alpha_e, frame)
        check_set_node_parent(tree, ch.decal_alpha_w, frame)
        check_set_node_parent(tree, ch.layer_intensity, frame)
        check_set_node_parent(tree, ch.intensity, frame)
        check_set_node_parent(tree, ch.extra_alpha, frame)
        check_set_node_parent(tree, ch.vdisp_blend, frame)
        check_set_node_parent(tree, ch.blend, frame)

        if root_ch.type == 'NORMAL':
            check_set_node_parent(tree, ch.spread_alpha, frame)
            check_set_node_parent(tree, ch.bump_distance_ignorer, frame)
            check_set_node_parent(tree, ch.tb_distance_flipper, frame)
            check_set_node_parent(tree, ch.tb_delta_calc, frame)
            check_set_node_parent(tree, ch.height_proc, frame)
            check_set_node_parent(tree, ch.height_blend, frame)
            check_set_node_parent(tree, ch.max_height_calc, frame)
            check_set_node_parent(tree, ch.normal_map_proc, frame)
            check_set_node_parent(tree, ch.normal_proc, frame)
            check_set_node_parent(tree, ch.normal_flip, frame)
            check_set_node_parent(tree, ch.vdisp_intensity, frame)
            check_set_node_parent(tree, ch.vdisp_flip_yz, frame)
            check_set_node_parent(tree, ch.vdisp_proc, frame)

    # Masks
    for i, mask in enumerate(layer.masks):
        frame = get_frame(tree, '__mask__', str(i), mask.name)

        if mask.group_node != '':
            check_set_node_parent(tree, mask.group_node, frame)
        else:
            check_set_node_parent(tree, mask.baked_source, frame)
            check_set_node_parent(tree, mask.source, frame)

        check_set_node_parent(tree, mask.uv_neighbor, frame)
        check_set_node_parent(tree, mask.uv_map, frame)

        check_set_node_parent(tree, mask.source_n, frame)
        check_set_node_parent(tree, mask.source_s, frame)
        check_set_node_parent(tree, mask.source_e, frame)
        check_set_node_parent(tree, mask.source_w, frame)

        check_set_node_parent(tree, mask.blur_vector, frame)
        check_set_node_parent(tree, mask.separate_color_channels, frame)
        check_set_node_parent(tree, mask.decal_process, frame)
        check_set_node_parent(tree, mask.decal_alpha, frame)
        check_set_node_parent(tree, mask.decal_alpha_n, frame)
        check_set_node_parent(tree, mask.decal_alpha_s, frame)
        check_set_node_parent(tree, mask.decal_alpha_e, frame)
        check_set_node_parent(tree, mask.decal_alpha_w, frame)
        check_set_node_parent(tree, mask.mapping, frame)
        check_set_node_parent(tree, mask.baked_mapping, frame)
        check_set_node_parent(tree, mask.texcoord, frame)

        for c in mask.channels:
            check_set_node_parent(tree, c.mix, frame)
            check_set_node_parent(tree, c.mix_pure, frame)
            check_set_node_parent(tree, c.mix_remains, frame)
            check_set_node_parent(tree, c.mix_limit, frame)
            check_set_node_parent(tree, c.mix_limit_normal, frame)

    clean_unused_frames(tree)
