# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection alpha processing - handles alpha and intensity operations.

This module provides alpha processing, intensity node handling, and mask multiply
functions for layer node reconnection. Extracted from the main reconnect_layer_nodes
function for modularity.
"""

from typing import TYPE_CHECKING, Any, Tuple

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....utils.common import get_entity_input_name, get_mix_color_indices
from ....utils.constants import (
    TREE_START,
)
from ..utils.io_utils import create_link
from ...node.node_utils import get_essential_node

if TYPE_CHECKING:
    from .layer_connections_context import LayerConnectionContext


def process_channel_mask_multiplies(
    ctx: "LayerConnectionContext",
    i: int,
    ch,
    root_ch,
    alpha: Any,
    intensity_multiplier,
    group_alpha: Any,
) -> Tuple[Any, Any]:
    """Process mask multiplications for a channel.

    Args:
        ctx: The LayerConnectionContext.
        i: The channel index.
        ch: The layer channel.
        root_ch: The root channel.
        alpha: Current alpha value.
        intensity_multiplier: The intensity multiplier node.
        group_alpha: Optional group alpha for limiting.

    Returns:
        Tuple of (updated_alpha, transition_input).
    """
    layer = ctx.layer
    tree = ctx.tree
    nodes = ctx.nodes
    chain = ctx.chain
    trans_bump_ch = ctx.trans_bump_ch

    transition_input = None

    # If chain is 0, apply intensity multiplier immediately
    if chain == 0 and intensity_multiplier:
        alpha = create_link(tree, alpha, intensity_multiplier.inputs[0])[0]

    # Process each mask
    for j, mask in enumerate(layer.masks):
        # Handle MODIFIER mask type
        if mask.type == "MODIFIER":
            if mask.group_node != "":
                mask_source = nodes.get(mask.group_node)
                if mask_source:
                    create_link(tree, alpha, mask_source.inputs[0])
            else:
                mask_source = nodes.get(mask.source)
                if mask_source:
                    if mask.modifier_type in {"CURVE", "INVERT"}:
                        create_link(tree, alpha, mask_source.inputs[1])
                    else:
                        create_link(tree, alpha, mask_source.inputs[0])

        # Get mask mix for this channel
        mask_mix = nodes.get(mask.channels[i].mix)
        if mask_mix:
            mmixcol0, mmixcol1, mmixout = get_mix_color_indices(mask_mix)
            alpha = create_link(tree, alpha, mask_mix.inputs[mmixcol0])[mmixout]

        # Handle mix_limit with group_alpha
        mix_limit = nodes.get(mask.channels[i].mix_limit)
        if mix_limit and group_alpha:
            alpha = create_link(tree, alpha, mix_limit.inputs[0])[0]
            create_link(tree, group_alpha, mix_limit.inputs[1])

        # At chain boundary, capture transition_input
        if j == chain - 1 and intensity_multiplier:
            transition_input = alpha
            alpha = create_link(tree, alpha, intensity_multiplier.inputs[0])[0]

    # If no trans_bump_ch, use final alpha as transition_input
    if not trans_bump_ch:
        transition_input = alpha

    return alpha, transition_input


def process_intensity_node(
    ctx: "LayerConnectionContext", ch, root_ch, intensity, alpha: Any, ch_intensity: Any
) -> Any:
    """Process intensity node (Channel Opacity).

    Connects alpha and ch_intensity to the intensity (Channel Opacity) node.
    For Normal channels, ch_intensity is the output of layer_intensity multiply.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        intensity: The intensity node.
        alpha: Current alpha value.
        ch_intensity: Channel intensity value (or layer_intensity output for Normal).

    Returns:
        Updated alpha value (intensity.outputs[0] - Channel Opacity output).
    """
    tree = ctx.tree
    layer = ctx.layer
    normal_proc = None

    logger.debug(f"process_intensity_node: layer={layer.name}, intensity={intensity.name if intensity else None}")
    logger.debug(f"  input alpha={alpha}, ch_intensity={ch_intensity}")

    # Get normal_proc for GROUP NORMAL check
    if root_ch.type == "NORMAL":
        normal_proc = tree.nodes.get(ch.normal_proc) if hasattr(ch, 'normal_proc') else None
        normal_alpha = getattr(ctx, 'normal_alpha', None)

        # For GROUP NORMAL without normal_proc, use normal_alpha
        if layer.type == 'GROUP' and not normal_proc and normal_alpha:
            alpha = create_link(tree, normal_alpha, intensity.inputs[0])[0]
            logger.debug(f"  Connected normal_alpha -> intensity.inputs[0], returning intensity.outputs[0]")
        else:
            alpha = create_link(tree, alpha, intensity.inputs[0])[0]
            logger.debug(f"  Connected alpha -> intensity.inputs[0], returning intensity.outputs[0]")
    else:
        alpha = create_link(tree, alpha, intensity.inputs[0])[0]
        logger.debug(f"  Connected alpha -> intensity.inputs[0], returning intensity.outputs[0]")

    # Connect ch_intensity to input[1] (Value input)
    if ch_intensity:
        create_link(tree, ch_intensity, intensity.inputs[1])
        logger.debug(f"  Connected ch_intensity -> intensity.inputs[1]")

    logger.debug(f"  Returning alpha={alpha} (should be intensity.outputs[0])")
    return alpha


def process_extra_alpha(ctx: "LayerConnectionContext", ch, extra_alpha, alpha: Any) -> Any:
    """Process extra alpha node.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        extra_alpha: The extra alpha node.
        alpha: Current alpha value.

    Returns:
        Updated alpha value.
    """
    tree = ctx.tree

    mixcol0, mixcol1, mixout = get_mix_color_indices(extra_alpha)
    alpha = create_link(tree, alpha, extra_alpha.inputs[mixcol0])[mixout]

    return alpha


def process_decal_alpha(
    ctx: "LayerConnectionContext", ch, root_ch, decal_alpha, alpha: Any
) -> Any:
    """Process decal alpha node.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        decal_alpha: The decal alpha node.
        alpha: Current alpha value.

    Returns:
        Updated alpha value.
    """
    layer = ctx.layer
    tree = ctx.tree
    decal_process = ctx.decal_process

    if decal_process:
        alpha = create_link(tree, alpha, decal_alpha.inputs[0])[0]
        create_link(tree, decal_process.outputs[1], decal_alpha.inputs[1])

    return alpha


def process_layer_intensity(ctx: "LayerConnectionContext", layer_intensity, ch_intensity: Any) -> Any:
    """Process layer intensity node (Layer Opacity multiply).

    Multiplies ch_intensity with layer_intensity_value:
    - ch_intensity -> layer_intensity.inputs[0]
    - layer_intensity_value -> layer_intensity.inputs[1]
    - Output goes to Channel Opacity node

    Args:
        ctx: The LayerConnectionContext.
        layer_intensity: The layer intensity node.
        ch_intensity: Channel intensity value.

    Returns:
        Output of layer_intensity multiply (ch_intensity * layer_intensity_value).
    """
    tree = ctx.tree

    # Connect ch_intensity to first input
    if ch_intensity:
        create_link(tree, ch_intensity, layer_intensity.inputs[0])

    # Connect layer_intensity_value to second input
    if ctx.layer_intensity_value:
        create_link(tree, ctx.layer_intensity_value, layer_intensity.inputs[1])

    # Return the output for use in Channel Opacity
    return layer_intensity.outputs[0]
