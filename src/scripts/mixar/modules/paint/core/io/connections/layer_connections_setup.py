# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection setup - initializes node references for layer reconnection.

This module provides setup functions that populate the LayerConnectionContext
with all necessary node references before the main reconnection logic runs.

Helper functions are organized into submodules for maintainability:
- setup_helpers.bump_setup: Tangent, bitangent, and bump process setup
- setup_helpers.vector_setup: Baked vector and texcoord vector setup
- setup_helpers.rgb_alpha_setup: RGB and alpha start value setup
- setup_helpers.channel_setup: Type-specific, UV neighbor, and channel setup
"""

from ......config.logging_config import get_logger
from ....utils.constants import ONE_VALUE, TREE_START
from ...layer.layer_utils import (
    get_root_height_channel,
    get_root_parallax_channel,
)
from ...node.node_utils import get_essential_node
from .layer_connections_context import LayerConnectionContext
from ..utils.source_connections import reconnect_source_internal_nodes

# Import helper functions from submodules
from ..setup_helpers.bump_setup import (
    setup_tangent_bitangent,
    setup_bump_process,
    setup_smooth_bump_heights,
)
from ..setup_helpers.vector_setup import (
    setup_baked_vector,
    setup_texcoord_vector,
    connect_vector_to_nodes,
)
from ..setup_helpers.rgb_alpha_setup import (
    setup_rgb_alpha_start,
    process_rgb_through_nodes,
    setup_modifier_outputs,
)
from ..setup_helpers.channel_setup import (
    setup_type_specific_nodes,
    setup_uv_neighbor_connections,
    setup_transition_bump,
    setup_height_channel,
)

logger = get_logger(__name__)


# Re-export helper functions with underscore prefix for backward compatibility
_setup_tangent_bitangent = setup_tangent_bitangent
_setup_bump_process = setup_bump_process
_setup_smooth_bump_heights = setup_smooth_bump_heights
_setup_baked_vector = setup_baked_vector
_setup_texcoord_vector = setup_texcoord_vector
_connect_vector_to_nodes = connect_vector_to_nodes
_setup_rgb_alpha_start = setup_rgb_alpha_start
_process_rgb_through_nodes = process_rgb_through_nodes
_setup_modifier_outputs = setup_modifier_outputs
_setup_type_specific_nodes = setup_type_specific_nodes
_setup_uv_neighbor_connections = setup_uv_neighbor_connections
_setup_transition_bump = setup_transition_bump
_setup_height_channel = setup_height_channel


def setup_layer_connection_context(ctx: LayerConnectionContext) -> None:
    """Initialize all node references in the context.

    This function populates the context with all the node references
    needed for layer reconnection. It handles source nodes, UV nodes,
    tangent/bitangent, and other initial setup.

    Args:
        ctx: The LayerConnectionContext to populate.
    """
    layer = ctx.layer
    mp = ctx.mp
    tree = ctx.tree
    nodes = ctx.nodes

    # Get source nodes
    source_group = nodes.get(layer.source_group)
    if source_group:
        ctx.source = source_group
        ctx.source_group = source_group
        reconnect_source_internal_nodes(layer)
    elif layer.type == "GROUP":
        # GROUP layers use the Start node as their source for _Group inputs
        ctx.source = tree.nodes.get(TREE_START)
    else:
        ctx.source = nodes.get(layer.source)

    # Debug logging for source setup
    if layer.type == "PROCEDURAL":
        logger.info(
            "SETUP_CTX: PROCEDURAL layer '%s', source_group='%s', source='%s', ctx.source=%s",
            layer.name, layer.source_group, layer.source, ctx.source
        )
        if ctx.source:
            outputs = [o.name for o in ctx.source.outputs]
            logger.info("SETUP_CTX: ctx.source outputs: %s", outputs)

    # Baked source
    if layer.use_baked:
        ctx.baked_source = nodes.get(layer.baked_source)

    # Direction sources
    ctx.source_n = nodes.get(layer.source_n)
    ctx.source_s = nodes.get(layer.source_s)
    ctx.source_e = nodes.get(layer.source_e)
    ctx.source_w = nodes.get(layer.source_w)

    # UV nodes
    ctx.uv_map = nodes.get(layer.uv_map)
    ctx.uv_neighbor = nodes.get(layer.uv_neighbor)
    ctx.uv_neighbor_1 = nodes.get(layer.uv_neighbor_1)

    # Coordinate nodes
    ctx.texcoord = nodes.get(layer.texcoord)
    ctx.blur_vector = nodes.get(layer.blur_vector)
    ctx.mapping = nodes.get(layer.mapping)
    ctx.linear = nodes.get(layer.linear)
    ctx.divider_alpha = nodes.get(layer.divider_alpha)
    ctx.flip_y = nodes.get(layer.flip_y)
    ctx.decal_process = nodes.get(layer.decal_process)

    # Setup root channels
    ctx.height_root_ch = get_root_height_channel(mp)
    ctx.parallax_root_ch = get_root_parallax_channel(mp)

    # Setup tangent and bitangent
    _setup_tangent_bitangent(ctx)

    # Setup bump process connections
    ctx.bump_process = nodes.get(layer.bump_process)
    _setup_bump_process(ctx)

    # Setup type-specific connections
    _setup_type_specific_nodes(ctx)

    # Setup baked vector
    _setup_baked_vector(ctx)

    # Setup texcoord vector
    _setup_texcoord_vector(ctx)

    # Setup RGB and alpha start values
    _setup_rgb_alpha_start(ctx)

    # Setup UV neighbor connections
    _setup_uv_neighbor_connections(ctx)

    # Setup transition bump channel
    _setup_transition_bump(ctx)

    # Setup height channel
    _setup_height_channel(ctx)

    # Initialize root mask value
    ctx.root_mask_val = get_essential_node(tree, ONE_VALUE)[0]


# Export all public functions and re-exported private functions
__all__ = [
    "setup_layer_connection_context",
    # Public helper functions
    "setup_tangent_bitangent",
    "setup_bump_process",
    "setup_smooth_bump_heights",
    "setup_baked_vector",
    "setup_texcoord_vector",
    "connect_vector_to_nodes",
    "setup_rgb_alpha_start",
    "process_rgb_through_nodes",
    "setup_modifier_outputs",
    "setup_type_specific_nodes",
    "setup_uv_neighbor_connections",
    "setup_transition_bump",
    "setup_height_channel",
    # Backward compatible underscore-prefixed aliases
    "_setup_tangent_bitangent",
    "_setup_bump_process",
    "_setup_smooth_bump_heights",
    "_setup_baked_vector",
    "_setup_texcoord_vector",
    "_connect_vector_to_nodes",
    "_setup_rgb_alpha_start",
    "_process_rgb_through_nodes",
    "_setup_modifier_outputs",
    "_setup_type_specific_nodes",
    "_setup_uv_neighbor_connections",
    "_setup_transition_bump",
    "_setup_height_channel",
]
