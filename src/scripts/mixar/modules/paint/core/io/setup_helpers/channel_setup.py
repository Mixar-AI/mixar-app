# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel and type-specific setup functions for layer connections.

This module provides setup functions for type-specific nodes, UV neighbor,
transition bump, and height channel connections during layer reconnection.
"""

from typing import TYPE_CHECKING

from ......config.logging_config import get_logger
from ....utils.common import get_entity_input_name
from ....utils.constants import GEOMETRY, TREE_START
from ..utils.io_utils import create_link
from ...layer.layer_utils import get_height_channel, get_transition_bump_channel
from ...node.node_utils import get_essential_node

if TYPE_CHECKING:
    from ..layer_connections_context import LayerConnectionContext

logger = get_logger(__name__)


def setup_type_specific_nodes(ctx: "LayerConnectionContext") -> None:
    """Setup type-specific node connections.

    Args:
        ctx: The LayerConnectionContext with layer, tree, source set.
    """
    layer = ctx.layer
    tree = ctx.tree
    source = ctx.source

    if layer.type == "EDGE_DETECT":
        edge_detect_radius_val = get_essential_node(tree, TREE_START).get(
            get_entity_input_name(layer, "edge_detect_radius")
        )
        if edge_detect_radius_val and source and "Radius" in source.inputs:
            create_link(tree, edge_detect_radius_val, source.inputs["Radius"])

    elif layer.type == "AO":
        ao_distance_val = get_essential_node(tree, TREE_START).get(
            get_entity_input_name(layer, "ao_distance")
        )
        if ao_distance_val and source and "Distance" in source.inputs:
            create_link(tree, ao_distance_val, source.inputs["Distance"])

    # Use previous normal for HEMI, EDGE_DETECT, AO
    if layer.type in {"HEMI", "EDGE_DETECT", "AO"} and source:
        if layer.hemi_use_prev_normal and ctx.bump_process:
            create_link(
                tree, ctx.bump_process.outputs["Normal"], source.inputs["Normal"]
            )
        elif "Normal" in source.inputs:
            create_link(
                tree,
                get_essential_node(tree, GEOMETRY)["Normal"],
                source.inputs["Normal"],
            )


def setup_uv_neighbor_connections(ctx: "LayerConnectionContext") -> None:
    """Setup UV neighbor vertex color connections.

    Args:
        ctx: The LayerConnectionContext with layer, tree, and related nodes set.
    """
    layer = ctx.layer
    tree = ctx.tree

    if layer.type not in {
        "VCOL",
        "GROUP",
        "HEMI",
        "OBJECT_INDEX",
        "EDGE_DETECT",
        "AO",
    }:
        return

    uv_neighbor = ctx.uv_neighbor
    if not uv_neighbor:
        return

    if (
        layer.type in {"VCOL", "HEMI", "OBJECT_INDEX", "EDGE_DETECT", "AO"}
        and ctx.start_rgb
    ):
        create_link(tree, ctx.start_rgb, uv_neighbor.inputs[0])

    if ctx.tangent and ctx.bitangent:
        if "Tangent" in uv_neighbor.inputs:
            create_link(tree, ctx.tangent, uv_neighbor.inputs["Tangent"])
        if "Bitangent" in uv_neighbor.inputs:
            create_link(tree, ctx.bitangent, uv_neighbor.inputs["Bitangent"])

    if layer.type == "VCOL" and ctx.uv_neighbor_1 and ctx.start_alpha:
        create_link(tree, ctx.start_alpha, ctx.uv_neighbor_1.inputs[0])

        if ctx.tangent and ctx.bitangent:
            if "Tangent" in ctx.uv_neighbor_1.inputs:
                create_link(tree, ctx.tangent, ctx.uv_neighbor_1.inputs["Tangent"])
            if "Bitangent" in ctx.uv_neighbor_1.inputs:
                create_link(tree, ctx.bitangent, ctx.uv_neighbor_1.inputs["Bitangent"])


def setup_transition_bump(ctx: "LayerConnectionContext") -> None:
    """Setup transition bump channel values.

    Populates the context with transition bump state:
    - trans_bump_ch: The transition bump channel
    - trans_bump_flip: Whether bump is flipped
    - trans_bump_crease: Whether bump has crease
    - chain: The transition bump chain length
    - tb_value: The transition bump value socket
    - tb_second_value: The second edge value socket

    Args:
        ctx: The LayerConnectionContext with layer and tree set.
    """
    layer = ctx.layer
    tree = ctx.tree

    trans_bump_ch = get_transition_bump_channel(layer)
    ctx.trans_bump_ch = trans_bump_ch

    if not trans_bump_ch:
        ctx.trans_bump_flip = False
        ctx.trans_bump_crease = False
        ctx.chain = -1
        ctx.tb_value = None
        ctx.tb_second_value = None
        return

    # Compute flip and crease flags
    ctx.trans_bump_flip = trans_bump_ch.transition_bump_flip
    ctx.trans_bump_crease = (
        trans_bump_ch.transition_bump_crease and not ctx.trans_bump_flip
    )

    # Compute chain length
    ctx.chain = min(len(layer.masks), trans_bump_ch.transition_bump_chain)

    # Get transition bump value sockets from tree start
    ctx.tb_value = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(trans_bump_ch, "transition_bump_value")
    )
    ctx.tb_second_value = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(trans_bump_ch, "transition_bump_second_edge_value")
    )


def setup_height_channel(ctx: "LayerConnectionContext") -> None:
    """Setup height channel connections.

    Also stores bump_smooth_multiplier_value in context for use by other helpers.

    Args:
        ctx: The LayerConnectionContext with layer, tree, nodes set.
    """
    layer = ctx.layer
    tree = ctx.tree

    height_ch = get_height_channel(layer)
    if not height_ch:
        ctx.bump_smooth_multiplier_value = None
        return

    # Setup UV neighbor multiplier
    bump_smooth_multiplier_value = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(height_ch, "bump_smooth_multiplier")
    )

    # Store in context for use by masks and channel processing
    ctx.bump_smooth_multiplier_value = bump_smooth_multiplier_value

    if not bump_smooth_multiplier_value:
        return

    if ctx.uv_neighbor and "Multiplier" in ctx.uv_neighbor.inputs:
        create_link(
            tree, bump_smooth_multiplier_value, ctx.uv_neighbor.inputs["Multiplier"]
        )

    if ctx.uv_neighbor_1 and "Multiplier" in ctx.uv_neighbor_1.inputs:
        create_link(
            tree, bump_smooth_multiplier_value, ctx.uv_neighbor_1.inputs["Multiplier"]
        )
