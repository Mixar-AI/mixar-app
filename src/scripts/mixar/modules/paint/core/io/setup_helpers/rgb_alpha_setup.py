# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""RGB and alpha setup functions for layer connections.

This module provides setup functions for RGB and alpha start values,
modifier outputs, and related processing during layer reconnection.
"""

from typing import TYPE_CHECKING

from ......config.logging_config import get_logger
from ....utils.common import get_mix_color_indices
from ....utils.constants import LAYER_ALPHA_VIEWER, ONE_VALUE, TREE_END
from ...element.modifier_utils import reconnect_all_modifier_nodes
from ..utils.io_utils import create_link
from ...node.node_utils import get_essential_node

if TYPE_CHECKING:
    from ..layer_connections_context import LayerConnectionContext

logger = get_logger(__name__)


def setup_rgb_alpha_start(ctx: "LayerConnectionContext") -> None:
    """Setup RGB and alpha start values.

    Args:
        ctx: The LayerConnectionContext with layer, tree, source set.
    """
    layer = ctx.layer
    tree = ctx.tree
    source = ctx.source

    # RGB start
    if ctx.baked_source:
        ctx.start_rgb = ctx.baked_source.outputs[0]
    elif (
        layer.type == "VORONOI"
        and layer.voronoi_feature == "N_SPHERE_RADIUS"
        and source
        and "Radius" in source.outputs
    ):
        ctx.start_rgb = source.outputs["Radius"]
    elif source and source.outputs:
        ctx.start_rgb = source.outputs[0]
    else:
        # Fallback when source is None or has no outputs
        ctx.start_rgb = None
        logger.debug("Source node is None or has no outputs, start_rgb set to None")

    # Check if procedural material:
    # - layer.type == "PROCEDURAL" for dedicated procedural layers
    # - layer.type == "COLOR" with source_type == "MATERIAL" for Fill layers with procedural materials
    ctx.proc_is_procedural = (
        layer.type == "PROCEDURAL" or
        (layer.type == "COLOR" and hasattr(layer, 'source_type') and layer.source_type == "MATERIAL")
    )

    # Alpha start
    if ctx.baked_source:
        ctx.start_alpha = ctx.baked_source.outputs[1]
    elif ctx.proc_is_procedural:
        if source and "Alpha" in source.outputs:
            ctx.start_alpha = source.outputs["Alpha"]
        else:
            ctx.start_alpha = get_essential_node(tree, ONE_VALUE)[0]
    elif layer.type == "IMAGE" or ctx.source_group or (
        layer.type == "COLOR"
        and hasattr(layer, "source_type")
        and layer.source_type == "IMAGE"
    ):
        # Use image alpha for IMAGE layers, source groups, and COLOR layers with IMAGE source
        ctx.start_alpha = (
            source.outputs[1] if source else get_essential_node(tree, ONE_VALUE)[0]
        )
    elif layer.type == "VCOL" and source and "Alpha" in source.outputs:
        ctx.start_alpha = source.outputs["Alpha"]
    else:
        ctx.start_alpha = get_essential_node(tree, ONE_VALUE)[0]

    ctx.alpha_preview = get_essential_node(tree, TREE_END).get(LAYER_ALPHA_VIEWER)

    # Process RGB through divider_alpha, linear, flip_y
    process_rgb_through_nodes(ctx)

    # Handle source group or modifier outputs
    setup_modifier_outputs(ctx)


def process_rgb_through_nodes(ctx: "LayerConnectionContext") -> None:
    """Process RGB through divider_alpha, linear, and flip_y nodes.

    Args:
        ctx: The LayerConnectionContext with source_group, tree, and start_rgb set.
    """
    if ctx.source_group:
        return

    tree = ctx.tree

    if ctx.divider_alpha and ctx.start_rgb:
        mixcol0, mixcol1, mixout = get_mix_color_indices(ctx.divider_alpha)
        ctx.start_rgb = create_link(
            tree, ctx.start_rgb, ctx.divider_alpha.inputs[mixcol0]
        )[mixout]
        create_link(tree, ctx.start_alpha, ctx.divider_alpha.inputs[mixcol1])

    if ctx.linear and ctx.start_rgb:
        ctx.start_rgb = create_link(tree, ctx.start_rgb, ctx.linear.inputs[0])[0]

    if ctx.flip_y and ctx.start_rgb:
        ctx.start_rgb = create_link(tree, ctx.start_rgb, ctx.flip_y.inputs[0])[0]


def setup_modifier_outputs(ctx: "LayerConnectionContext") -> None:
    """Setup modifier outputs for RGB and alpha.

    Args:
        ctx: The LayerConnectionContext with layer, tree, nodes, source set.
    """
    layer = ctx.layer
    tree = ctx.tree
    nodes = ctx.nodes
    source = ctx.source

    start_rgb_1 = None
    start_alpha_1 = get_essential_node(tree, ONE_VALUE)[0]

    if (
        layer.type
        not in {"COLOR", "HEMI", "OBJECT_INDEX", "MUSGRAVE", "EDGE_DETECT", "AO", "PROCEDURAL"}
        and source
        and len(source.outputs) > 1
    ):
        start_rgb_1 = source.outputs[1]

    if ctx.source_group and layer.type not in {
        "IMAGE",
        "VCOL",
        "BACKGROUND",
        "HEMI",
        "OBJECT_INDEX",
        "MUSGRAVE",
        "EDGE_DETECT",
        "AO",
    }:
        if len(ctx.source_group.outputs) > 3:
            start_rgb_1 = ctx.source_group.outputs[2]
            start_alpha_1 = ctx.source_group.outputs[3]

    elif not ctx.source_group:
        mod_group = nodes.get(layer.mod_group)

        if layer.type not in {"BACKGROUND", "GROUP"}:
            ctx.start_rgb, ctx.start_alpha = reconnect_all_modifier_nodes(
                tree, layer, ctx.start_rgb, ctx.start_alpha, mod_group
            )

        if layer.type not in {
            "IMAGE",
            "VCOL",
            "BACKGROUND",
            "COLOR",
            "GROUP",
            "HEMI",
            "OBJECT_INDEX",
            "MUSGRAVE",
            "EDGE_DETECT",
            "AO",
            "PROCEDURAL",
        }:
            mod_group_1 = nodes.get(layer.mod_group_1)
            if source and len(source.outputs) > 1:
                start_rgb_1, start_alpha_1 = reconnect_all_modifier_nodes(
                    tree,
                    layer,
                    source.outputs[1],
                    get_essential_node(tree, ONE_VALUE)[0],
                    mod_group_1,
                )
