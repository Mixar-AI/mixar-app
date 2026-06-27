# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection main - orchestrates layer node reconnection.

This module provides the main entry point for layer node reconnection.
It uses helper modules for setup, mask processing, and channel processing.
"""

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
    LAYER_ALPHA_VIEWER,
    limited_mask_blend_types,
)
from ..utils.io_utils import break_input_link, break_link, create_link
from ...layer.check_layers import (
    check_need_prev_normal,
    get_channel_enabled,
    has_previous_layer_channels,
)
from ...node.node_utils import clean_essential_nodes, get_essential_node
from ...subtree.get_subtree import get_upper_neighbor, has_channel_children

# Import context and helper modules
from .layer_connections_context import LayerConnectionContext, create_layer_connection_context
from .layer_connections_setup import setup_layer_connection_context
from .layer_connections_masks import process_layer_masks_ctx
from .layer_connections_channels import (
    initialize_channel_state,
    get_channel_intensity,
    get_prev_channel_values,
    initialize_end_chain_variables,
    setup_group_channel_outputs,
    setup_background_channel_outputs,
)
from .layer_connections_blend import (
    process_blend_node,
    process_vdisp_blend,
    process_alpha_output,
    process_layer_preview,
)
from ..utils.source_connections import reconnect_channel_source_internal_nodes
from .layer_connections_normal import process_normal_channel
from .layer_connections_source import (
    process_group_channel,
    process_channel_source_type,
    process_procedural_channel,
    process_channel_override,
    connect_intensity_multiplier,
    process_group_normal_channel,
    process_channel_modifiers,
    process_normal_override,
)
from .layer_connections_alpha import (
    process_channel_mask_multiplies,
    process_intensity_node,
    process_extra_alpha,
    process_decal_alpha,
    process_layer_intensity,
)


def reconnect_layer_nodes(layer, ch_idx=-1, merge_mask=False):
    """Reconnect all nodes within a layer's node tree.

    This is the main orchestrator function for reconnecting layer nodes.
    It coordinates setup, mask processing, and channel processing phases.

    Args:
        layer: The layer object containing node references and configuration.
        ch_idx: Channel index to reconnect (-1 for all). Default is -1.
        merge_mask: Whether to merge mask connections. Default is False.

    Returns:
        None
    """
    mp = layer.id_data.mp

    if mp.halt_reconnect:
        return

    # Create and populate context
    ctx = create_layer_connection_context(layer, ch_idx, merge_mask)
    setup_layer_connection_context(ctx)

    # Process masks
    process_layer_masks_ctx(ctx)

    # Early return for merge_mask preview
    if merge_mask and mp.layer_preview_mode:
        if ctx.alpha_preview:
            create_link(ctx.tree, ctx.root_mask_val, ctx.alpha_preview)
        return

    # Process channels
    _process_layer_channels(ctx)

    # Clean unused essential nodes
    clean_essential_nodes(ctx.tree, exclude_texcoord=True)


def _process_layer_channels(ctx: LayerConnectionContext) -> None:
    """Process all layer channels for reconnection.

    This handles per-channel RGB/alpha setup, transition bump, height/normal
    processing, mask multiplies, and blend connections.

    Args:
        ctx: The LayerConnectionContext with all needed state.
    """
    layer = ctx.layer
    mp = ctx.mp
    tree = ctx.tree
    nodes = ctx.nodes

    # Layer intensity input
    ctx.layer_intensity_value = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(layer, "intensity_value")
    )

    # Parent flag
    ctx.has_parent = layer.parent_idx != -1

    # Get start values for secondary outputs
    start_rgb_1, start_alpha_1 = _get_secondary_start_values(ctx)

    # Process each channel
    for i, ch in enumerate(layer.channels):
        # Bounds check: ensure index is valid for mp.channels
        if i >= len(mp.channels):
            logger.warning("Channel index %d out of bounds for mp.channels (length: %d)", i, len(mp.channels))
            continue

        root_ch = mp.channels[i]

        # Initialize channel and check if should process
        state = initialize_channel_state(ctx, ch, root_ch, i)
        if state is None:
            continue

        rgb, alpha = state

        # Process this channel
        _process_single_channel(
            ctx, i, ch, root_ch, rgb, alpha, start_rgb_1, start_alpha_1
        )


def _get_secondary_start_values(ctx: LayerConnectionContext):
    """Get secondary RGB/alpha start values for multi-output sources."""
    layer = ctx.layer
    tree = ctx.tree
    source = ctx.source

    start_rgb_1 = None
    start_alpha_1 = get_essential_node(tree, ONE_VALUE)[0]

    if (
        layer.type not in {"COLOR", "HEMI", "OBJECT_INDEX", "MUSGRAVE", "EDGE_DETECT", "AO", "PROCEDURAL"}
        and source
        and len(source.outputs) > 1
    ):
        start_rgb_1 = source.outputs[1]

    if ctx.source_group and layer.type not in {
        "IMAGE", "VCOL", "BACKGROUND", "HEMI", "OBJECT_INDEX", "MUSGRAVE", "EDGE_DETECT", "AO", "PROCEDURAL"
    }:
        if len(ctx.source_group.outputs) > 3:
            start_rgb_1 = ctx.source_group.outputs[2]
            start_alpha_1 = ctx.source_group.outputs[3]

    return start_rgb_1, start_alpha_1


def _process_single_channel(
    ctx: LayerConnectionContext,
    i: int,
    ch,
    root_ch,
    rgb,
    alpha,
    start_rgb_1,
    start_alpha_1,
) -> None:
    """Process a single channel's node connections."""
    layer = ctx.layer
    mp = ctx.mp
    tree = ctx.tree
    nodes = ctx.nodes
    source = ctx.source

    ch_intensity = get_channel_intensity(ctx, ch)
    prev_rgb, prev_alpha = get_prev_channel_values(ctx, root_ch)

    # Initialize per-channel variables
    bg_alpha = None
    prev_vdisp = None
    next_vdisp = None
    prev_vdisp_alpha = None
    next_vdisp_alpha = None
    group_vdisp = None
    vdisp_alpha = None
    height_alpha = None
    normal_alpha = None
    group_alpha = None

    ch_uv_neighbor = nodes.get(ch.uv_neighbor)

    # Handle GROUP layer type
    if layer.type == "GROUP":
        rgb, alpha, group_vdisp, vdisp_alpha = process_group_channel(
            ctx, ch, root_ch, source, rgb, alpha
        )
        group_alpha = alpha

    # Handle BACKGROUND layer type
    elif layer.type == "BACKGROUND":
        rgb, alpha, bg_alpha = setup_background_channel_outputs(ctx, root_ch, source)

    # Process source index and RGB/alpha based on layer type
    rgb, alpha, source_index = process_channel_source_type(
        ctx, layer, ch, root_ch, rgb, alpha, start_rgb_1, start_alpha_1
    )

    rgb_before_override = rgb

    # Handle per-channel override based on override_type
    # Process override when type is OVERRIDE, IMAGE, or for legacy DEFAULT mode
    # For NORMAL channels with NORMAL_MAP type, we skip override processing here
    # as they use the normal-specific override (override_1)
    override_type = getattr(ch, 'override_type', 'LAYER')
    should_process_override = override_type in ('OVERRIDE', 'IMAGE', 'DEFAULT') or getattr(ch, 'override', False)
    if should_process_override and (root_ch.type != "NORMAL" or ch.normal_map_type != "NORMAL_MAP"):
        rgb = process_channel_override(ctx, ch, root_ch, ch_uv_neighbor, rgb)

    normal = rgb_before_override

    # Process normal map override (source_1) for NORMAL_MAP and BUMP_NORMAL_MAP modes
    if root_ch.type == "NORMAL" and ch.override_1 and ch.normal_map_type in ("NORMAL_MAP", "BUMP_NORMAL_MAP"):
        normal = process_normal_override(ctx, ch, normal)

    # Skip if not the target channel
    if ctx.ch_idx != -1 and i != ctx.ch_idx:
        return

    # Get blend-related nodes
    intensity = nodes.get(ch.intensity)
    layer_intensity = nodes.get(ch.layer_intensity)
    intensity_multiplier = nodes.get(ch.intensity_multiplier)
    extra_alpha = nodes.get(ch.extra_alpha)
    decal_alpha = nodes.get(ch.decal_alpha)
    blend = nodes.get(ch.blend)

    # Check if normal is overridden - for NORMAL_MAP mode with override_1,
    # normal already holds the correct value from process_normal_override
    if root_ch.type == "NORMAL" and ch.normal_map_type == "NORMAL_MAP":
        rgb = normal

    # Connect intensity multiplier
    connect_intensity_multiplier(ctx, ch, intensity_multiplier)

    # Process channel linear
    if ch.source_group == "":
        ch_linear = nodes.get(ch.linear)
        if ch_linear:
            create_link(tree, rgb, ch_linear.inputs[0])
            rgb = ch_linear.outputs[0]

    # Process modifiers
    mod_group = nodes.get(ch.mod_group)
    rgb_before_mod = rgb
    alpha_before_mod = alpha

    # Process based on layer type
    if layer.type == "BACKGROUND":
        pass
    elif layer.type == "GROUP" and root_ch.type == "NORMAL":
        normal, normal_alpha = process_group_normal_channel(
            ctx, ch, root_ch, source, normal
        )
        # Store normal_alpha in context for intensity node processing (ucupaint pattern)
        ctx.normal_alpha = normal_alpha
    else:
        rgb, alpha = process_channel_modifiers(
            ctx, ch, root_ch, mod_group, rgb, alpha
        )

    alpha_after_mod = alpha

    # Get channel-specific values
    ch_bump_distance = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(ch, "bump_distance")
    )
    ch_bump_midlevel = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(ch, "bump_midlevel")
    )

    # Initialize end chain variables
    initialize_end_chain_variables(ctx, alpha_after_mod)

    # Preserve the genuine pre-mask alpha (after modifiers, before masks) so the
    # smooth-bump neighbor defaults can still recover it after end_chain is
    # overwritten with the mask-multiplied alpha during mask processing.
    ctx.alpha_after_mod = alpha_after_mod

    # Process mask multiplies for this channel
    alpha, transition_input = process_channel_mask_multiplies(
        ctx, i, ch, root_ch, alpha, intensity_multiplier, group_alpha
    )

    # Store transition input
    ctx.transition_input = transition_input

    # Fetch height-related variables for NORMAL channels
    prev_height = None
    prev_height_alpha = None
    next_height = None
    next_height_alpha = None
    prev_height_n = None
    prev_height_s = None
    prev_height_e = None
    prev_height_w = None

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

        # Smooth bump neighbor heights
        if root_ch.enable_smooth_bump:
            prev_height_n = get_essential_node(tree, TREE_START).get(
                root_ch.name + io_suffix["HEIGHT_N"]
            )
            prev_height_s = get_essential_node(tree, TREE_START).get(
                root_ch.name + io_suffix["HEIGHT_S"]
            )
            prev_height_e = get_essential_node(tree, TREE_START).get(
                root_ch.name + io_suffix["HEIGHT_E"]
            )
            prev_height_w = get_essential_node(tree, TREE_START).get(
                root_ch.name + io_suffix["HEIGHT_W"]
            )

    # Process height/normal specific logic
    vdisp_processed = None  # VDM processed output for VECTOR_DISPLACEMENT_MAP mode
    if root_ch.type == "NORMAL":
        rgb, alpha, normal, vdisp_processed, ch_intensity = process_normal_channel(
            ctx, ch, root_ch, rgb, alpha, normal, normal_alpha,
            ch_intensity, ch_bump_distance, ch_bump_midlevel,
            layer_intensity, intensity_multiplier,
            prev_height, prev_height_alpha, next_height, next_height_alpha,
            prev_height_n, prev_height_s, prev_height_e, prev_height_w
        )
    else:
        # For non-Normal channels, multiply ch_intensity with layer_intensity_value
        # through layer_intensity node BEFORE passing to Channel Opacity
        # Flow: ch_intensity * layer_intensity_value -> Channel Opacity Value input
        if layer_intensity:
            ch_intensity = process_layer_intensity(
                ctx, layer_intensity, ch_intensity
            )

    # Process intensity nodes (Channel Opacity)
    # alpha -> inputs[0], ch_intensity (or layer_intensity output) -> inputs[1]
    # output -> blend Fac
    if intensity:
        alpha = process_intensity_node(
            ctx, ch, root_ch, intensity, alpha, ch_intensity
        )

    # Process extra alpha
    if extra_alpha:
        alpha = process_extra_alpha(ctx, ch, extra_alpha, alpha)

    # Process decal alpha
    if decal_alpha:
        alpha = process_decal_alpha(ctx, ch, root_ch, decal_alpha, alpha)

    # Get next outputs
    next_rgb = get_essential_node(tree, TREE_END).get(root_ch.name)
    next_alpha = get_essential_node(tree, TREE_END).get(
        root_ch.name + io_suffix["ALPHA"]
    )

    # Get vdisp nodes
    vdisp_blend = nodes.get(ch.vdisp_blend)
    if root_ch.type == "NORMAL":
        prev_vdisp = get_essential_node(tree, TREE_START).get(
            root_ch.name + io_suffix["VDISP"]
        )
        next_vdisp = get_essential_node(tree, TREE_END).get(
            root_ch.name + io_suffix["VDISP"]
        )
        prev_vdisp_alpha = get_essential_node(tree, TREE_START).get(
            root_ch.name + io_suffix["VDISP"] + io_suffix["ALPHA"]
        )
        next_vdisp_alpha = get_essential_node(tree, TREE_END).get(
            root_ch.name + io_suffix["VDISP"] + io_suffix["ALPHA"]
        )

    # Process normal proc
    normal_proc = nodes.get(ch.normal_proc)

    # For VDM mode with write_height=False, use vdisp_processed output for blend node
    # This ensures the processed VDM texture goes through the blend node
    blend_rgb = rgb
    if (root_ch.type == "NORMAL" and
        ch.normal_map_type == "VECTOR_DISPLACEMENT_MAP" and
        not get_write_height(ch) and
        vdisp_processed):
        blend_rgb = vdisp_processed

    # Process blend node
    process_blend_node(
        ctx, ch, root_ch, blend, blend_rgb, alpha, normal, normal_alpha,
        prev_rgb, prev_alpha, next_rgb, next_alpha, bg_alpha, normal_proc
    )

    # Process vdisp blend
    if prev_vdisp_alpha and next_vdisp_alpha:
        create_link(tree, prev_vdisp_alpha, next_vdisp_alpha)

    if vdisp_blend:
        # Use processed VDM output for VECTOR_DISPLACEMENT_MAP mode
        vdisp_rgb = vdisp_processed if vdisp_processed else rgb
        process_vdisp_blend(
            ctx, ch, root_ch, vdisp_blend, vdisp_rgb, alpha, vdisp_alpha,
            group_vdisp, prev_vdisp, next_vdisp, prev_vdisp_alpha,
            next_vdisp_alpha, ch_intensity
        )
    elif prev_vdisp and next_vdisp:
        create_link(tree, prev_vdisp, next_vdisp)

    # Process alpha output
    process_alpha_output(
        ctx, ch, root_ch, blend, prev_alpha, next_alpha
    )

    # Layer preview
    if mp.layer_preview_mode:
        process_layer_preview(
            ctx, ch, root_ch, i, rgb, alpha, normal_proc
        )
