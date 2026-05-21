# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer node arrangement helper functions.

This module contains helper functions for arranging layer nodes including
source nodes, mapping nodes, UV/neighbor nodes, and mask nodes.
"""

from mathutils import Vector

from ....utils.constants import limited_mask_blend_types
from ...node.loc import check_set_node_loc

# Re-export cache functions for backward compatibility
from .layer_arrangements_cache import (
    arrange_layer_cache_nodes,
    arrange_channel_cache_nodes,
    arrange_mask_cache_nodes,
)

# Re-export blend functions for backward compatibility
from .layer_arrangements_blend import (
    arrange_channel_blend_nodes,
)


def arrange_source_nodes(layer, tree, loc):
    """Arrange source nodes for the layer.

    Positions source group, bump process, baked source, main source,
    directional sources, and UV neighbor nodes.

    Args:
        layer: The layer object containing source node references.
        tree: The node tree containing the source nodes.
        loc (Vector): The starting location for arranging nodes (modified in place).

    Returns:
        Vector: The updated location after arranging all source nodes.
    """
    if layer.source_group != '':
        if check_set_node_loc(tree, layer.source_group, loc):
            loc.x += 330

    bookmark_x = loc.x

    if check_set_node_loc(tree, layer.bump_process, loc):
        loc.y -= 400

    if check_set_node_loc(tree, layer.baked_source, loc, hide=False):
        loc.y -= 280

    if check_set_node_loc(tree, layer.source, loc, hide=False):
        loc.y -= 280

    for attr in ['source_n', 'source_s', 'source_e', 'source_w']:
        if check_set_node_loc(tree, getattr(layer, attr), loc, True):
            loc.y -= 40

    loc.y = 0
    loc.x += 280

    if check_set_node_loc(tree, layer.uv_neighbor, loc):
        loc.y -= 320

    if check_set_node_loc(tree, layer.uv_neighbor_1, loc):
        loc.y -= 320

    loc.y = 0
    loc.x += 180

    return loc


def arrange_mapping_nodes(layer, tree, loc):
    """Arrange mapping and coordinate nodes.

    Positions mapping, baked mapping, blur vector, divider alpha, linear,
    flip Y, decal process, UV map, and texcoord nodes.

    Args:
        layer: The layer object containing mapping node references.
        tree: The node tree containing the mapping nodes.
        loc (Vector): The starting location for arranging nodes (modified in place).

    Returns:
        Vector: The updated location after arranging all mapping nodes.
    """
    if check_set_node_loc(tree, layer.mapping, loc):
        loc.y -= 370

    if check_set_node_loc(tree, layer.baked_mapping, loc):
        loc.y -= 370

    if check_set_node_loc(tree, layer.blur_vector, loc):
        loc.y -= 140

    if check_set_node_loc(tree, layer.divider_alpha, loc):
        loc.y -= 170

    if check_set_node_loc(tree, layer.linear, loc):
        loc.y -= 170

    if check_set_node_loc(tree, layer.flip_y, loc):
        loc.y -= 170

    if check_set_node_loc(tree, layer.decal_process, loc):
        loc.y -= 170

    if check_set_node_loc(tree, layer.uv_map, loc):
        loc.y -= 130

    if check_set_node_loc(tree, layer.texcoord, loc):
        loc.y -= 210

    loc.y = 0
    loc.x += 200

    return loc


def arrange_uv_neighbor_nodes(layer, tree, loc):
    """Arrange UV neighbor and channel-specific source nodes.

    Channels can have override sources (source_group) in certain configurations.
    This function safely checks for these attributes before arranging.

    Args:
        layer: The layer object containing channels with source node references.
        tree: The node tree containing the UV/source nodes.
        loc (Vector): The starting location for arranging nodes (modified in place).

    Returns:
        Vector: The updated location after arranging all UV/source nodes.
    """
    bookmark_x = loc.x

    # Channel source attributes that may exist for override sources
    channel_source_attrs = [
        ('source_group', 330, 0),      # (attr, x_offset, y_offset)
        ('baked_source', 0, 280),
        ('source', 0, 280),
        ('uv_neighbor', 0, 320),
        ('mapping', 0, 370),
        ('baked_mapping', 0, 370),
        ('blur_vector', 0, 140),
        ('linear', 0, 170),
        ('flip_y', 0, 170),
        ('uv_map', 0, 130),
        ('texcoord', 0, 210),
    ]

    for i, ch in enumerate(layer.channels):
        loc.x = bookmark_x

        for attr, x_off, y_off in channel_source_attrs:
            if hasattr(ch, attr):
                node_name = getattr(ch, attr, '')
                if node_name and check_set_node_loc(tree, node_name, loc, hide=(y_off < 200)):
                    if x_off > 0:
                        loc.x += x_off
                    if y_off > 0:
                        loc.y -= y_off

    loc.y = 0
    loc.x += 200

    return loc


def arrange_mask_nodes(layer, mp, tree, nodes, loc, bump_ch, flip_bump, chain, y_step, farthest_x,
                       rearrange_mask_tree_nodes_func, arrange_mask_modifier_nodes_func,
                       rearrange_transition_bump_nodes_func):
    """Arrange mask nodes and their channels.

    Positions all mask-related nodes including sources, modifiers, mix nodes,
    and transition effects for each mask in the layer.

    Args:
        layer: The layer object containing masks to arrange.
        mp: The MPaint object containing channel information.
        tree: The node tree containing the mask nodes.
        nodes: The nodes collection from the tree.
        loc (Vector): The starting location for arranging nodes (modified in place).
        bump_ch: The bump channel for transition effects, or None.
        flip_bump (bool): Whether bump is flipped for transition effects.
        chain (int): The transition bump chain length.
        y_step (int): The vertical step size between channels.
        farthest_x (float): The current farthest X position.
        rearrange_mask_tree_nodes_func: Function to rearrange mask tree nodes.
        arrange_mask_modifier_nodes_func: Function to arrange mask modifier nodes.
        rearrange_transition_bump_nodes_func: Function to rearrange transition bump nodes.

    Returns:
        tuple: (updated_loc, updated_farthest_x)
    """
    for i, mask in enumerate(layer.masks):
        loc.y = 0

        rearrange_mask_tree_nodes_func(mask)

        # Mask source nodes
        loc = _arrange_mask_source_nodes(tree, mask, loc)

        loc.y = 0
        loc.x += 270
        check_set_node_loc(tree, mask.separate_color_channels, loc)

        if mask.group_node == '' and len(mask.modifiers) > 0:
            loc.x += 270
            arrange_mask_modifier_nodes_func(tree, mask, loc)
            loc.x += 20
        else:
            loc.x += 370

        bookmark_x = loc.x

        if check_set_node_loc(tree, mask.mix, loc, True):
            loc.y -= 40

        # Mask channels
        loc, farthest_x = _arrange_mask_channel_nodes(
            layer, mp, tree, mask, i, loc, bump_ch, flip_bump, chain, farthest_x, bookmark_x,
            rearrange_transition_bump_nodes_func
        )

    return loc, farthest_x


def _arrange_mask_source_nodes(tree, mask, loc):
    """Arrange mask source and mapping nodes.

    Helper function to arrange source-related nodes for a mask.

    Args:
        tree: The node tree containing the nodes.
        mask: The mask object containing node references.
        loc (Vector): The current location (modified in place).

    Returns:
        Vector: The updated location after arranging mask source nodes.
    """
    if mask.group_node != '':
        if check_set_node_loc(tree, mask.group_node, loc):
            loc.x += 330
    else:
        if check_set_node_loc(tree, mask.linear, loc):
            loc.y -= 140

        if check_set_node_loc(tree, mask.baked_source, loc):
            loc.y -= 270

        if check_set_node_loc(tree, mask.source, loc):
            loc.y -= 270

    for attr in ['source_n', 'source_s', 'source_e', 'source_w']:
        if check_set_node_loc(tree, getattr(mask, attr), loc, True):
            loc.y -= 40

    if check_set_node_loc(tree, mask.uv_neighbor, loc):
        loc.y -= 320

    if check_set_node_loc(tree, mask.mapping, loc):
        loc.y -= 360

    if check_set_node_loc(tree, mask.baked_mapping, loc):
        loc.y -= 360

    if check_set_node_loc(tree, mask.blur_vector, loc):
        loc.y -= 140

    if check_set_node_loc(tree, mask.decal_process, loc):
        loc.y -= 170

    if check_set_node_loc(tree, mask.uv_map, loc):
        loc.y -= 130

    if check_set_node_loc(tree, mask.texcoord, loc):
        loc.y -= 170

    return loc


def _arrange_mask_channel_nodes(layer, mp, tree, mask, mask_idx, loc, bump_ch, flip_bump, chain,
                                farthest_x, bookmark_x, rearrange_transition_bump_nodes_func):
    """Arrange mask channel nodes for a single mask.

    Helper function to arrange channel-specific nodes within a mask.

    Args:
        layer: The layer object containing the mask.
        mp: The MPaint object containing channel information.
        tree: The node tree containing the nodes.
        mask: The mask being processed.
        mask_idx (int): The index of the mask in the layer.
        loc (Vector): The current location (modified in place).
        bump_ch: The bump channel for transition effects, or None.
        flip_bump (bool): Whether bump is flipped.
        chain (int): The transition bump chain length.
        farthest_x (float): The current farthest X position.
        bookmark_x (float): The bookmark X position for this mask.
        rearrange_transition_bump_nodes_func: Function to rearrange transition bump nodes.

    Returns:
        tuple: (updated_loc, updated_farthest_x)
    """
    for j, c in enumerate(mask.channels):
        ch = layer.channels[j]
        root_ch = mp.channels[j]

        if root_ch.type == 'NORMAL':
            local_chain = min(len(layer.masks), ch.transition_bump_chain)
        elif bump_ch:
            local_chain = min(len(layer.masks), bump_ch.transition_bump_chain)
        else:
            local_chain = -1

        loc.x = bookmark_x
        bookmark_y = loc.y

        # Arrange mix nodes
        loc = _arrange_mask_mix_nodes(tree, c, root_ch, layer, mask, loc)

        loc.x += 230
        bookmark_y1 = loc.y
        loc.y = bookmark_y

        # Transition effects
        if mask_idx == local_chain - 1 and bump_ch:
            ch = layer.channels[j]
            loc = _arrange_transition_effect_nodes(
                tree, ch, layer, loc, bump_ch, flip_bump,
                rearrange_transition_bump_nodes_func
            )
        else:
            loc.y = bookmark_y1

        if loc.x > farthest_x:
            farthest_x = loc.x

    return loc, farthest_x


def _arrange_mask_mix_nodes(tree, c, root_ch, layer, mask, loc):
    """Arrange mask channel mix nodes.

    Helper function to arrange mix nodes for a mask channel.

    Args:
        tree: The node tree containing the nodes.
        c: The mask channel object.
        root_ch: The root channel from mp.channels.
        layer: The layer containing the mask.
        mask: The mask being processed.
        loc (Vector): The current location (modified in place).

    Returns:
        Vector: The updated location after arranging mix nodes.
    """
    mix_pure = tree.nodes.get(c.mix_pure)
    mix_remains = tree.nodes.get(c.mix_remains)
    mix_normal = tree.nodes.get(c.mix_normal)
    mix_vdisp = tree.nodes.get(c.mix_vdisp)
    mix_limit_normal = tree.nodes.get(c.mix_limit_normal)

    if mix_pure or mix_remains or mix_normal or mix_limit_normal or mix_vdisp:
        for attr in ['mix', 'mix_pure', 'mix_remains', 'mix_normal', 'mix_vdisp', 'mix_limit_normal']:
            if check_set_node_loc(tree, getattr(c, attr), loc, True):
                loc.y -= 40

    if check_set_node_loc(tree, c.mix, loc):
        if root_ch.type == 'NORMAL' and root_ch.enable_smooth_bump:
            if layer.type == 'GROUP' and mask.blend_type in limited_mask_blend_types:
                loc.y -= 540.0
            else:
                loc.y -= 430.0
        else:
            loc.y -= 240.0

    if check_set_node_loc(tree, c.mix_limit, loc, True):
        loc.y -= 40

    return loc


def _arrange_transition_effect_nodes(tree, ch, layer, loc, bump_ch, flip_bump,
                                     rearrange_transition_bump_nodes_func):
    """Arrange transition effect nodes for a channel.

    Helper function to arrange transition bump and ramp effect nodes.

    Args:
        tree: The node tree containing the nodes.
        ch: The channel object.
        layer: The layer containing the channel.
        loc (Vector): The current location (modified in place).
        bump_ch: The bump channel for transition effects.
        flip_bump (bool): Whether bump is flipped.
        rearrange_transition_bump_nodes_func: Function to rearrange transition bump nodes.

    Returns:
        Vector: The updated location after arranging transition effect nodes.
    """
    if check_set_node_loc(tree, ch.intensity_multiplier, loc, False):
        loc.y -= 200

    if flip_bump and check_set_node_loc(tree, ch.tao, loc, False):
        loc.y -= 230

    if ch.enable_transition_ramp and (
        (not ch.transition_ramp_intensity_unlink or flip_bump or ch.transition_ramp_blend_type != 'MIX')
        and not (layer.parent_idx != -1 and layer.type == 'BACKGROUND' and ch.transition_ramp_blend_type == 'MIX')
    ):
        if check_set_node_loc(tree, ch.tr_ramp, loc):
            loc.y -= 230

    if bump_ch == ch:
        rearrange_transition_bump_nodes_func(tree, ch, loc)
        loc.y -= 300

    return loc
