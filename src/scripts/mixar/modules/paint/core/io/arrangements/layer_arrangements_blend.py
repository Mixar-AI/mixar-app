# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel blend node arrangement functions.

This module handles the arrangement of channel blend nodes including
TAO, transition ramps, decal alpha, intensity, and normal processing nodes.
"""

from ...node.loc import check_set_node_loc


def arrange_channel_blend_nodes(layer, mp, tree, loc, bump_ch, flip_bump, chain, farthest_x):
    """Arrange channel blend nodes.

    Positions all channel blend nodes including TAO, transition ramp blend,
    decal alpha, layer intensity, normal processing nodes, and final blend nodes.

    Args:
        layer: The layer object containing channels to arrange.
        mp: The MPaint object containing channel information.
        tree: The node tree containing the blend nodes.
        loc (Vector): The starting location for arranging nodes (modified in place).
        bump_ch: The bump channel for transition effects, or None.
        flip_bump (bool): Whether bump is flipped for transition effects.
        chain (int): The transition bump chain length.
        farthest_x (float): The current farthest X position.

    Returns:
        tuple: (updated_loc, updated_farthest_x)
    """
    bookmark_x = loc.x

    for i, ch in enumerate(layer.channels):
        root_ch = mp.channels[i]
        loc.x = bookmark_x

        y_offset = 240

        if not flip_bump and check_set_node_loc(tree, ch.tao, loc):
            loc.x += 200
            y_offset += 120

        # Flipped transition ramp
        if bump_ch and flip_bump:
            if check_set_node_loc(tree, ch.tr_ramp_blend, loc):
                loc.x += 200
                y_offset += 90

        if root_ch.type == 'NORMAL' and root_ch.enable_smooth_bump and layer.texcoord_type == 'Decal':
            ori_y = loc.y
            for attr in ['decal_alpha', 'decal_alpha_n', 'decal_alpha_s', 'decal_alpha_e', 'decal_alpha_w']:
                if check_set_node_loc(tree, getattr(ch, attr), loc, True):
                    loc.y -= 40
            loc.x += 200
            loc.y = ori_y
        elif check_set_node_loc(tree, ch.decal_alpha, loc):
            loc.x += 200

        if check_set_node_loc(tree, ch.layer_intensity, loc):
            loc.x += 200

        if root_ch.type == 'NORMAL':
            loc = _arrange_normal_channel_nodes(tree, ch, loc)

        if check_set_node_loc(tree, ch.intensity, loc):
            loc.x += 200

        bookmark_x1 = loc.x

        if (
            (ch.enable_transition_ramp and not flip_bump and ch.transition_ramp_intensity_unlink
             and ch.transition_ramp_blend_type == 'MIX')
            or (layer.parent_idx != -1 and layer.type == 'BACKGROUND' and ch.transition_ramp_blend_type == 'MIX')
        ):
            if check_set_node_loc(tree, ch.tr_ramp, loc):
                loc.x += 200

        if check_set_node_loc(tree, ch.extra_alpha, loc):
            loc.x += 200

        if check_set_node_loc(tree, ch.vdisp_blend, loc):
            loc.x += 200

        if check_set_node_loc(tree, ch.blend, loc):
            loc.x += 250

        if loc.x > farthest_x:
            farthest_x = loc.x

        loc.y -= y_offset

    return loc, farthest_x


def _arrange_normal_channel_nodes(tree, ch, loc):
    """Arrange normal channel specific nodes.

    Helper function to arrange nodes specific to NORMAL type channels.

    Args:
        tree: The node tree containing the nodes.
        ch: The channel object containing normal node references.
        loc (Vector): The current location (modified in place).

    Returns:
        Vector: The updated location after arranging normal channel nodes.
    """
    if check_set_node_loc(tree, ch.bump_distance_ignorer, loc):
        loc.x += 200
    if check_set_node_loc(tree, ch.tb_distance_flipper, loc):
        loc.x += 200
    if check_set_node_loc(tree, ch.tb_delta_calc, loc):
        loc.x += 200
    if check_set_node_loc(tree, ch.spread_alpha, loc):
        loc.x += 200
    if check_set_node_loc(tree, ch.height_proc, loc):
        loc.x += 200
    if check_set_node_loc(tree, ch.height_blend, loc):
        loc.x += 200
    if check_set_node_loc(tree, ch.max_height_calc, loc):
        loc.x += 200
    if check_set_node_loc(tree, ch.normal_map_proc, loc):
        loc.x += 200
    if check_set_node_loc(tree, ch.normal_proc, loc):
        loc.x += 200
    if check_set_node_loc(tree, ch.normal_flip, loc):
        loc.x += 200
    if check_set_node_loc(tree, ch.vdisp_intensity, loc):
        loc.x += 200
    if check_set_node_loc(tree, ch.vdisp_flip_yz, loc):
        loc.x += 200
    if check_set_node_loc(tree, ch.vdisp_proc, loc):
        loc.x += 200

    return loc
