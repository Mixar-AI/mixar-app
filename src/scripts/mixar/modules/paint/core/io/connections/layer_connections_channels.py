# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection channel processing - handles channel node reconnection.

This module provides channel processing functions for layer node reconnection.
Extracted from the main reconnect_layer_nodes function for modularity.

The channel processing phase is the most complex part of layer reconnection,
handling:
- Per-channel RGB/alpha setup
- Transition bump connections
- Height/normal processing
- End chain variable management
- Mask multiplies per channel
"""

from typing import TYPE_CHECKING, Any, Optional, Tuple

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....utils.common import get_entity_input_name, get_mix_color_indices, get_write_height
from ....utils.constants import (
    GEOMETRY,
    ONE_VALUE,
    TREE_END,
    TREE_START,
    ZERO_VALUE,
    io_suffix,
    LAYER_VIEWER,
)
from ..utils.io_utils import break_input_link, break_link, create_link
from ...layer.check_layers import get_channel_enabled
from ...node.node_utils import get_essential_node

if TYPE_CHECKING:
    from .layer_connections_context import LayerConnectionContext


def initialize_channel_state(
    ctx: "LayerConnectionContext", ch, root_ch, i: int
) -> Optional[Tuple[Any, Any]]:
    """Initialize channel state and check if channel should be processed.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        i: The channel index.

    Returns:
        Tuple of (rgb, alpha) start values, or None if channel should be skipped.
    """
    layer = ctx.layer
    mp = ctx.mp
    tree = ctx.tree
    nodes = ctx.nodes

    # Check if channel is enabled
    if not get_channel_enabled(ch, layer, root_ch):
        # Handle disabled channel preview
        if mp.layer_preview_mode:
            _handle_disabled_channel_preview(ctx, ch, root_ch, mp, i)

        # Create passthrough connections for disabled channels
        # This ensures previous layer values pass through when channel is disabled
        _create_disabled_channel_passthrough(ctx, root_ch)

        return None

    # Initialize RGB and alpha from context start values
    rgb = ctx.start_rgb
    alpha = ctx.start_alpha

    return rgb, alpha


def _create_disabled_channel_passthrough(ctx: "LayerConnectionContext", root_ch) -> None:
    """Create passthrough connections for a disabled channel.

    When a channel is disabled on a layer, we need to connect the previous layer's
    output directly to the next layer's input, ensuring the value passes through
    unchanged instead of being lost.

    Args:
        ctx: The LayerConnectionContext.
        root_ch: The root channel.
    """
    tree = ctx.tree

    # Get previous layer's output (input to this layer)
    prev_rgb = get_essential_node(tree, TREE_START).get(root_ch.name)
    prev_alpha = get_essential_node(tree, TREE_START).get(
        root_ch.name + io_suffix["ALPHA"]
    )

    # Get next layer's input (output from this layer)
    next_rgb = get_essential_node(tree, TREE_END).get(root_ch.name)
    next_alpha = get_essential_node(tree, TREE_END).get(
        root_ch.name + io_suffix["ALPHA"]
    )

    # Break existing connections to outputs before creating passthrough
    # This ensures we don't have competing connections from blend nodes
    if next_rgb:
        break_input_link(tree, next_rgb)
    if next_alpha:
        break_input_link(tree, next_alpha)

    # Create passthrough connections
    if prev_rgb and next_rgb:
        create_link(tree, prev_rgb, next_rgb)
    if prev_alpha and next_alpha:
        create_link(tree, prev_alpha, next_alpha)

    # Handle height passthrough for NORMAL channels
    if root_ch.type == "NORMAL":
        prev_height = get_essential_node(tree, TREE_START).get(
            root_ch.name + io_suffix["HEIGHT"]
        )
        prev_height_alpha = get_essential_node(tree, TREE_START).get(
            root_ch.name + io_suffix["HEIGHT"] + io_suffix["ALPHA"]
        )
        next_height = get_essential_node(tree, TREE_END).get(
            root_ch.name + io_suffix["HEIGHT"]
        )
        next_height_alpha = get_essential_node(tree, TREE_END).get(
            root_ch.name + io_suffix["HEIGHT"] + io_suffix["ALPHA"]
        )

        # Break existing links before creating passthrough
        if next_height:
            break_input_link(tree, next_height)
        if next_height_alpha:
            break_input_link(tree, next_height_alpha)

        if prev_height and next_height:
            create_link(tree, prev_height, next_height)
        if prev_height_alpha and next_height_alpha:
            create_link(tree, prev_height_alpha, next_height_alpha)

        # Handle vector displacement passthrough
        prev_vdisp = get_essential_node(tree, TREE_START).get(
            root_ch.name + io_suffix["VDISP"]
        )
        prev_vdisp_alpha = get_essential_node(tree, TREE_START).get(
            root_ch.name + io_suffix["VDISP"] + io_suffix["ALPHA"]
        )
        next_vdisp = get_essential_node(tree, TREE_END).get(
            root_ch.name + io_suffix["VDISP"]
        )
        next_vdisp_alpha = get_essential_node(tree, TREE_END).get(
            root_ch.name + io_suffix["VDISP"] + io_suffix["ALPHA"]
        )

        # Break existing links before creating passthrough
        if next_vdisp:
            break_input_link(tree, next_vdisp)
        if next_vdisp_alpha:
            break_input_link(tree, next_vdisp_alpha)

        if prev_vdisp and next_vdisp:
            create_link(tree, prev_vdisp, next_vdisp)
        if prev_vdisp_alpha and next_vdisp_alpha:
            create_link(tree, prev_vdisp_alpha, next_vdisp_alpha)


def _handle_disabled_channel_preview(ctx, ch, root_ch, mp, i):
    """Handle preview mode for disabled channels."""
    tree = ctx.tree
    alpha_preview = ctx.alpha_preview

    if root_ch == mp.channels[mp.active_channel_index]:
        col_preview = get_essential_node(tree, TREE_END).get(LAYER_VIEWER)
        if col_preview:
            create_link(
                tree, get_essential_node(tree, ZERO_VALUE)[0], col_preview
            )
        if alpha_preview:
            create_link(
                tree, get_essential_node(tree, ZERO_VALUE)[0], alpha_preview
            )


def get_channel_intensity(ctx: "LayerConnectionContext", ch) -> Any:
    """Get the channel intensity value from tree start.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.

    Returns:
        The channel intensity socket, or None.
    """
    return get_essential_node(ctx.tree, TREE_START).get(
        get_entity_input_name(ch, "intensity_value")
    )


def get_prev_channel_values(ctx: "LayerConnectionContext", root_ch) -> Tuple[Any, Any]:
    """Get previous RGB and alpha values for a channel.

    Args:
        ctx: The LayerConnectionContext.
        root_ch: The root channel.

    Returns:
        Tuple of (prev_rgb, prev_alpha) sockets.
    """
    tree = ctx.tree
    prev_rgb = get_essential_node(tree, TREE_START).get(root_ch.name)
    prev_alpha = get_essential_node(tree, TREE_START).get(
        root_ch.name + io_suffix["ALPHA"]
    )
    return prev_rgb, prev_alpha


def initialize_end_chain_variables(
    ctx: "LayerConnectionContext",
    alpha_after_mod: Any,
    alpha_n: Any = None,
    alpha_s: Any = None,
    alpha_e: Any = None,
    alpha_w: Any = None,
) -> None:
    """Initialize end chain variables in context.

    These variables track the alpha state at the end of the transition bump chain.

    Args:
        ctx: The LayerConnectionContext to update.
        alpha_after_mod: The alpha value after modifier processing.
        alpha_n/s/e/w: Direction-specific alpha values for smooth bump.
    """
    ctx.end_chain = alpha_after_mod
    ctx.end_chain_n = alpha_n
    ctx.end_chain_s = alpha_s
    ctx.end_chain_e = alpha_e
    ctx.end_chain_w = alpha_w

    ctx.end_chain_crease = alpha_after_mod
    ctx.end_chain_crease_n = alpha_n
    ctx.end_chain_crease_s = alpha_s
    ctx.end_chain_crease_e = alpha_e
    ctx.end_chain_crease_w = alpha_w


def process_mask_multiply_for_channel(
    ctx: "LayerConnectionContext",
    i: int,
    alpha: Any,
    intensity_multiplier: Any = None,
    group_alpha: Any = None,
) -> Tuple[Any, Any]:
    """Process mask multiplications for a single channel.

    This handles the per-channel mask mixing that happens during channel
    processing, including chain-aware alpha multiplying.

    Args:
        ctx: The LayerConnectionContext.
        i: The channel index.
        alpha: The current alpha value.
        intensity_multiplier: Optional intensity multiplier node.
        group_alpha: Optional group alpha for limiting.

    Returns:
        Tuple of (updated_alpha, transition_input).
    """
    layer = ctx.layer
    tree = ctx.tree
    nodes = ctx.nodes
    chain = ctx.chain
    transition_input = None

    # If chain is 0, apply intensity multiplier immediately
    if chain == 0 and intensity_multiplier:
        alpha = create_link(tree, alpha, intensity_multiplier.inputs[0])[0]

    # Process each mask
    for j, mask in enumerate(layer.masks):
        # Handle MODIFIER mask type
        if mask.type == "MODIFIER":
            alpha = _process_modifier_mask_alpha(
                tree, nodes, mask, alpha
            )

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
    if not ctx.trans_bump_ch:
        transition_input = alpha

    return alpha, transition_input


def _process_modifier_mask_alpha(tree, nodes, mask, alpha):
    """Process alpha through a MODIFIER type mask."""
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
    return alpha


def setup_group_channel_outputs(
    ctx: "LayerConnectionContext", root_ch, source
) -> Tuple[Any, Any, Any, Any]:
    """Setup outputs for GROUP layer channels.

    Args:
        ctx: The LayerConnectionContext.
        root_ch: The root channel.
        source: The source node.

    Returns:
        Tuple of (rgb, alpha, group_vdisp, vdisp_alpha).
    """
    layer = ctx.layer
    ch = None
    for ch_candidate in layer.channels:
        if ch_candidate == root_ch:
            ch = ch_candidate
            break

    rgb = ctx.start_rgb
    alpha = ctx.start_alpha
    group_vdisp = None
    vdisp_alpha = None

    if not source:
        return rgb, alpha, group_vdisp, vdisp_alpha

    if root_ch.type == "NORMAL":
        # Check if transition bump is enabled for this channel
        ch_enable_transition_bump = False
        for layer_ch in layer.channels:
            if layer_ch.enable_transition_bump:
                ch_enable_transition_bump = True
                break

        if ch_enable_transition_bump:
            group_height = source.outputs.get(
                root_ch.name + io_suffix["HEIGHT"] + io_suffix["GROUP"]
            )
            if group_height:
                rgb = group_height
        else:
            group_channel = source.outputs.get(root_ch.name + io_suffix["GROUP"])
            if group_channel:
                rgb = group_channel

        group_height_alpha = source.outputs.get(
            root_ch.name
            + io_suffix["HEIGHT"]
            + io_suffix["ALPHA"]
            + io_suffix["GROUP"]
        )
        if group_height_alpha:
            alpha = group_height_alpha
    else:
        group_channel = source.outputs.get(root_ch.name + io_suffix["GROUP"])
        if group_channel:
            rgb = group_channel

        group_channel_alpha = source.outputs.get(
            root_ch.name + io_suffix["ALPHA"] + io_suffix["GROUP"]
        )
        if group_channel_alpha:
            alpha = group_channel_alpha

    # Vector displacement from group
    group_vdisp = source.outputs.get(
        root_ch.name + io_suffix["VDISP"] + io_suffix["GROUP"]
    )
    vdisp_alpha = source.outputs.get(
        root_ch.name
        + io_suffix["VDISP"]
        + io_suffix["ALPHA"]
        + io_suffix["GROUP"]
    )

    return rgb, alpha, group_vdisp, vdisp_alpha


def setup_background_channel_outputs(
    ctx: "LayerConnectionContext", root_ch, source
) -> Tuple[Any, Any, Any]:
    """Setup outputs for BACKGROUND layer channels.

    Args:
        ctx: The LayerConnectionContext.
        root_ch: The root channel.
        source: The source node.

    Returns:
        Tuple of (rgb, alpha, bg_alpha).
    """
    tree = ctx.tree
    rgb = ctx.start_rgb
    alpha = get_essential_node(tree, ONE_VALUE)[0]
    bg_alpha = None

    if source:
        source_rgb = source.outputs.get(root_ch.name + io_suffix["BACKGROUND"])
        if source_rgb:
            rgb = source_rgb

        if root_ch.enable_alpha:
            bg_alpha = source.outputs.get(
                root_ch.name + io_suffix["ALPHA"] + io_suffix["BACKGROUND"]
            )

    return rgb, alpha, bg_alpha


def connect_height_proc_inputs(
    ctx: "LayerConnectionContext",
    height_proc,
    ch_intensity: Any,
    ch_bump_distance: Any,
    ch_bump_midlevel: Any,
) -> None:
    """Connect inputs to height_proc node.

    Args:
        ctx: The LayerConnectionContext.
        height_proc: The height processor node.
        ch_intensity: Channel intensity socket.
        ch_bump_distance: Bump distance socket.
        ch_bump_midlevel: Bump midlevel socket.
    """
    tree = ctx.tree

    if ch_intensity and "Intensity" in height_proc.inputs:
        create_link(tree, ch_intensity, height_proc.inputs["Intensity"])

    if ch_bump_distance and "Value Max Height" in height_proc.inputs:
        create_link(tree, ch_bump_distance, height_proc.inputs["Value Max Height"])

    if ch_bump_midlevel and "Midlevel" in height_proc.inputs:
        create_link(tree, ch_bump_midlevel, height_proc.inputs["Midlevel"])
