# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""MP node arrangement functions for layer tree organization.

This module handles the arrangement of MPaint group tree nodes including
UV nodes, start/end nodes, channels, and modifiers.
"""

from mathutils import Vector

from ....utils.constants import (
    BAKED_PARALLAX,
    BAKED_PARALLAX_FILTER,
    GEOMETRY,
    ONE_VALUE,
    PARALLAX,
    PARALLAX_PREP_SUFFIX,
    TEXCOORD,
    TREE_END,
    TREE_START,
    ZERO_VALUE,
    texcoord_lists,
)
from ...element.frame_utils import rearrange_mp_frame_nodes
from ...node.loc import check_set_node_loc
from .layer_arrangements_parallax import rearrange_parallax_process_internal_nodes


def rearrange_uv_nodes(group_tree, loc):
    """Arrange UV and texture coordinate related nodes.

    Positions texture coordinate, geometry, parallax, tangent, bitangent,
    and UV map nodes vertically from the given location.

    Args:
        group_tree: The group node tree containing UV nodes.
        loc (Vector): The starting location for arranging nodes (modified in place).

    Returns:
        None
    """
    mp = group_tree.mp

    if check_set_node_loc(group_tree, TEXCOORD, loc):
        loc.y -= 240

    if check_set_node_loc(group_tree, GEOMETRY, loc):
        loc.y -= 240

    if check_set_node_loc(group_tree, PARALLAX, loc):
        rearrange_parallax_process_internal_nodes(group_tree, PARALLAX)
        loc.y -= 240

    if check_set_node_loc(group_tree, BAKED_PARALLAX_FILTER, loc):
        loc.y -= 180

    if check_set_node_loc(group_tree, BAKED_PARALLAX, loc):
        rearrange_parallax_process_internal_nodes(group_tree, BAKED_PARALLAX)
        loc.y -= 240

    for uv in mp.uvs:

        if check_set_node_loc(group_tree, uv.parallax_prep, loc):
            loc.y -= 280

        if check_set_node_loc(group_tree, uv.temp_tangent, loc):
            loc.y -= 180

        if check_set_node_loc(group_tree, uv.temp_bitangent, loc):
            loc.y -= 180

        if check_set_node_loc(group_tree, uv.tangent_flip, loc):
            loc.y -= 180

        if check_set_node_loc(group_tree, uv.bitangent_flip, loc):
            loc.y -= 120

        if check_set_node_loc(group_tree, uv.tangent, loc):
            loc.y -= 160

        if check_set_node_loc(group_tree, uv.bitangent, loc):
            loc.y -= 160

        if check_set_node_loc(group_tree, uv.tangent_process, loc):
            loc.y -= 160

        if check_set_node_loc(group_tree, uv.uv_map, loc):
            loc.y -= 120

    for tc in texcoord_lists:
        if check_set_node_loc(group_tree, tc + PARALLAX_PREP_SUFFIX, loc):
            loc.y -= 280


def rearrange_mp_nodes(group_tree):
    """Arrange all MPaint nodes in the main group tree.

    Positions all nodes in the MPaint system including start nodes, layer nodes,
    channel nodes, modifiers, baked outputs, and end nodes in a comprehensive
    horizontal and vertical layout.

    Args:
        group_tree: The main MPaint group node tree to organize.

    Returns:
        None
    """
    # Import here to avoid circular imports
    from ...element.frame_utils import check_set_node_width
    from ...subtree.get_subtree import get_list_of_parent_ids
    from .layer_arrangements_parallax import rearrange_depth_layer_nodes

    mp = group_tree.mp
    nodes = group_tree.nodes

    loc = Vector((-200, 0))

    # Rearrange depth layer nodes
    rearrange_depth_layer_nodes(group_tree)

    # Rearrange start nodes
    check_set_node_loc(group_tree, TREE_START, loc)

    loc.x += 200
    ori_x = loc.x

    num_channels = len(mp.channels)

    # Start nodes
    for i, channel in enumerate(mp.channels):

        # Start nodes
        if check_set_node_loc(group_tree, channel.start_linear, loc):
            if channel.type == 'RGB':
                loc.y -= 110
            elif channel.type == 'VALUE':
                loc.y -= 170

        if check_set_node_loc(group_tree, channel.start_normal_filter, loc):
            loc.y -= 120

        if check_set_node_loc(group_tree, channel.start_bump_process, loc):
            loc.y -= 250

        if i == num_channels - 1:
            if check_set_node_loc(group_tree, ONE_VALUE, loc):
                loc.y -= 90
            if check_set_node_loc(group_tree, ZERO_VALUE, loc):
                loc.y -= 90
            check_set_node_loc(group_tree, GEOMETRY, loc)

            # Rearrange uv nodes
            rearrange_uv_nodes(group_tree, loc)

    loc.x += 200
    loc.y = 0.0

    # Layer nodes
    for i, t in enumerate(reversed(mp.layers)):

        parent_ids = get_list_of_parent_ids(t)

        loc.y = len(parent_ids) * -250

        tnode = group_tree.nodes.get(t.group_node)
        check_set_node_width(tnode, 300)

        if check_set_node_loc(group_tree, t.group_node, loc):
            loc.x += 350

    farthest_x = ori_x = loc.x

    # Import arrange_modifier_nodes from modifier module to avoid circular imports
    from .layer_arrangements_modifier import arrange_modifier_nodes

    # Modifiers
    for i, channel in enumerate(mp.channels):

        loc.x = ori_x

        loc, offset_y = arrange_modifier_nodes(
            group_tree, channel, loc,
            is_value=channel.type == 'VALUE',
            return_y_offset=True
        )

        if loc.x > farthest_x:
            farthest_x = loc.x
        loc.y -= offset_y

    loc.x = farthest_x
    loc.y = 0.0

    # End nodes
    for i, channel in enumerate(mp.channels):

        if check_set_node_loc(group_tree, channel.end_linear, loc):
            if channel.type == 'RGB':
                loc.y -= 110
            elif channel.type == 'VALUE':
                loc.y -= 170
            elif channel.type == 'NORMAL':
                loc.y -= 300

        if check_set_node_loc(group_tree, channel.clamp, loc):
            loc.y -= 240

        if check_set_node_loc(group_tree, channel.end_max_height_tweak, loc):
            loc.y -= 220

        if check_set_node_loc(group_tree, channel.end_backface, loc):
            loc.y -= 180

    loc.x += 200
    loc.y = 0.0

    farthest_x = ori_x = loc.x

    for i, ch in enumerate(mp.channels):

        loc.x = ori_x

        if check_set_node_loc(group_tree, ch.baked, loc):
            loc.x += 270

        if mp.use_baked and check_set_node_loc(group_tree, channel.end_normal_engine_filter, loc):
            loc.x += 200

        if check_set_node_loc(group_tree, ch.baked_normal_prep, loc):
            loc.x += 200

        if check_set_node_loc(group_tree, ch.baked_normal, loc):
            loc.x += 200

        loc.y -= 270
        save_x = loc.x

        loc.x = ori_x

        if check_set_node_loc(group_tree, ch.baked_normal_overlay, loc):
            loc.y -= 270

        if check_set_node_loc(group_tree, ch.baked_disp, loc):
            loc.y -= 270

        if check_set_node_loc(group_tree, ch.end_max_height, loc):
            loc.y -= 110

        if check_set_node_loc(group_tree, ch.baked_vdisp, loc):
            loc.y -= 270

        if check_set_node_loc(group_tree, ch.baked_vcol, loc):
            loc.y -= 270

        loc.x = save_x

        if loc.x > farthest_x:
            farthest_x = loc.x

    for bt in mp.bake_targets:

        loc.x = ori_x

        if check_set_node_loc(group_tree, bt.image_node, loc):
            loc.x += 200

        loc.y -= 270

        if loc.x > farthest_x:
            farthest_x = loc.x

    loc.x = farthest_x
    loc.y = 0

    # End node
    check_set_node_loc(group_tree, TREE_END, loc)

    # Rearrange frames
    rearrange_mp_frame_nodes(mp)
