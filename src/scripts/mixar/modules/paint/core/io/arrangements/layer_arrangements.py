# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer arrangement functions for node tree organization.

This module is the main entry point for layer arrangement functions.
The actual implementations are split across helper modules for maintainability.
"""

from mathutils import Vector

from ....utils.constants import (
    TREE_END,
    TREE_START,
)
from ...element.frame_utils import check_set_node_width
from ...layer.layer_utils import get_transition_bump_channel
from ...node.loc import check_set_node_loc
from ...subtree.get_subtree import get_tree

# Re-export parallax arrangement functions for backward compatibility
from .layer_arrangements_parallax import (
    rearrange_depth_layer_nodes,
    rearrange_parallax_iteration,
    rearrange_parallax_depth_group,
    rearrange_parallax_layer_nodes_,
    rearrange_parallax_process_internal_nodes,
)

# Re-export mask arrangement functions for backward compatibility
from .layer_arrangements_mask import (
    arrange_mask_modifier_nodes,
    rearrange_mask_tree_nodes,
)

# Re-export modifier arrangement functions
from .layer_arrangements_modifier import (
    NO_MODIFIER_Y_OFFSET,
    FINE_BUMP_Y_OFFSET,
    default_y_offsets,
    mod_y_offsets,
    value_mod_y_offsets,
    get_mod_y_offsets,
    arrange_modifier_nodes,
)

# Re-export frame arrangement functions
from .layer_arrangements_frame import rearrange_layer_frame_nodes

# Re-export source tree arrangement functions
from .layer_arrangements_source import (
    rearrange_source_tree_nodes,
    rearrange_channel_source_tree_nodes,
    rearrange_transition_bump_nodes,
)

# Re-export MP arrangement functions
from .layer_arrangements_mp import (
    rearrange_uv_nodes,
    rearrange_mp_nodes,
)

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

# Re-export layer helper functions for backward compatibility
from .layer_arrangements_layer import (
    arrange_source_nodes,
    arrange_mapping_nodes,
    arrange_uv_neighbor_nodes,
    arrange_mask_nodes,
)

# Import for local use in rearrange_layer_nodes
from .layer_arrangements_source import rearrange_transition_bump_nodes as _rearrange_transition_bump_nodes
from .layer_arrangements_mask import rearrange_mask_tree_nodes as _rearrange_mask_tree_nodes
from .layer_arrangements_mask import arrange_mask_modifier_nodes as _arrange_mask_modifier_nodes


def rearrange_layer_nodes(layer, tree=None):
    """Arrange all nodes within a layer's node tree.

    Comprehensive arrangement of all layer components including caches, sources,
    mappings, UV nodes, channels, modifiers, masks, and blend nodes. Positions
    nodes horizontally and vertically based on their type and relationships.

    Args:
        layer: The layer object whose nodes will be arranged.
        tree (optional): The node tree to organize. If None, retrieves tree from layer.
            Defaults to None.

    Returns:
        None
    """
    mp = layer.id_data.mp

    if mp.halt_reconnect:
        return

    if not tree:
        tree = get_tree(layer)
    nodes = tree.nodes

    # Get transition bump channel
    flip_bump = False
    chain = -1
    bump_ch = get_transition_bump_channel(layer)
    if bump_ch:
        flip_bump = bump_ch.transition_bump_flip
        chain = min(len(layer.masks), bump_ch.transition_bump_chain)

    # Back to source nodes
    loc = Vector((0, 0))

    # Start node
    check_set_node_loc(tree, TREE_START, loc)

    start = tree.nodes.get(TREE_START)
    check_set_node_width(start, 250)

    if start:
        loc.y = -(len(start.outputs) * 25)

    # Arrange cache nodes
    loc = arrange_layer_cache_nodes(layer, tree, loc)
    loc = arrange_channel_cache_nodes(layer, tree, loc)
    loc = arrange_mask_cache_nodes(layer, tree, loc)

    # Move to next column
    loc.x += 300
    loc.y = 0

    # Arrange source and mapping nodes
    loc = arrange_source_nodes(layer, tree, loc)
    loc = arrange_mapping_nodes(layer, tree, loc)

    # Arrange UV and neighbor nodes
    loc = arrange_uv_neighbor_nodes(layer, tree, loc)

    # Calculate y step for channels
    y_step = default_y_offsets.get(mp.channels[0].type, 165) if len(mp.channels) > 0 else 165
    y_mid = -(len(layer.channels) * y_step) / 2

    bookmark_x = loc.x
    farthest_x = loc.x

    # Arrange masks
    loc, farthest_x = arrange_mask_nodes(
        layer, mp, tree, nodes, loc, bump_ch, flip_bump, chain, y_step, farthest_x,
        _rearrange_mask_tree_nodes, _arrange_mask_modifier_nodes, _rearrange_transition_bump_nodes
    )

    loc.x = farthest_x
    loc.y = 0
    bookmark_x = loc.x

    # Arrange transition ramp for non-bump channels
    for i, ch in enumerate(layer.channels):
        loc.x = bookmark_x

        if not bump_ch and ch.enable_transition_ramp:
            if check_set_node_loc(tree, ch.tr_ramp, loc):
                loc.x += 200

        if loc.x > farthest_x:
            farthest_x = loc.x
        loc.y -= y_step

    loc.x = farthest_x
    loc.y = 0
    bookmark_x = loc.x

    # Arrange channel blends
    loc, farthest_x = arrange_channel_blend_nodes(
        layer, mp, tree, loc, bump_ch, flip_bump, chain, farthest_x
    )

    loc.x = farthest_x
    loc.y = 0

    check_set_node_loc(tree, TREE_END, loc)

    rearrange_layer_frame_nodes(layer, tree)


# Keep backward-compatible aliases with underscore prefix for internal use
_arrange_layer_cache_nodes = arrange_layer_cache_nodes
_arrange_channel_cache_nodes = arrange_channel_cache_nodes
_arrange_mask_cache_nodes = arrange_mask_cache_nodes
_arrange_source_nodes = arrange_source_nodes
_arrange_mapping_nodes = arrange_mapping_nodes
_arrange_uv_neighbor_nodes = arrange_uv_neighbor_nodes
_arrange_mask_nodes = arrange_mask_nodes
_arrange_channel_blend_nodes = arrange_channel_blend_nodes
