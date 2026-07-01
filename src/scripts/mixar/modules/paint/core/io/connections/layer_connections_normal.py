# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection normal - handles normal channel processing.

This module provides the process_normal_channel function for handling
NORMAL type channel connections including height processing, smooth bump,
and transition bump features.

The implementation is split across helper modules:
- layer_connections_normal_neighbors: Smooth bump neighbor setup
- layer_connections_normal_transition: Transition bump connections
- layer_connections_normal_height: Height processor and blend connections
"""

from ......config.logging_config import get_logger
from ....utils.common import get_entity_input_name, get_mix_color_indices, get_write_height
from ....utils.constants import TREE_START, TREE_END, io_suffix
from ..utils.io_utils import create_link
from ...node.node_utils import get_essential_node

# Re-export all functions from helper modules for backward compatibility
from .layer_connections_normal_neighbors import (
    initialize_neighbor_values,
    get_source_neighbor_nodes,
    setup_neighbor_values_from_source,
    setup_neighbor_values_from_uv,
    setup_neighbor_values_from_group,
    setup_neighbor_values_for_transition_bump,
    process_modifier_nodes_for_neighbors,
    setup_all_neighbor_values,
)

from .layer_connections_normal_transition import (
    connect_transition_bump_distance,
    connect_transition_bump_crease,
    connect_transition_bump_no_crease,
    connect_transition_bump_inverse,
    connect_standard_alpha,
    process_transition_bump_connections,
)

from .layer_connections_normal_height import (
    connect_height_proc_value_inputs,
    connect_height_proc_parameters,
    connect_normal_map_proc_input,
    connect_normal_proc_input,
    connect_normal_proc_parameters,
    get_height_alpha_output,
    get_blend_alpha_output,
    connect_height_blend_standard,
    connect_height_blend_smooth_bump,
    connect_smooth_bump_height_outputs,
    connect_height_blend_to_normal_proc,
    connect_height_proc_to_normal_proc,
    determine_final_rgb_output,
    connect_max_height_calc,
)

logger = get_logger(__name__)


def process_vdisp_channel(ctx, ch, rgb):
    """Process vector displacement channel connections.

    Connects painted VDM texture through vdisp_flip_yz and vdisp_proc nodes
    for proper VDM processing before blending.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        rgb: Current RGB value (painted VDM texture).

    Returns:
        Processed VDM output socket (goes to vdisp_blend).
    """
    tree = ctx.tree
    nodes = tree.nodes

    vdisp_flip_yz = nodes.get(ch.vdisp_flip_yz)
    vdisp_proc = nodes.get(ch.vdisp_proc)

    vdisp_output = rgb

    # Apply Y/Z flip if enabled (for Blender VDM compatibility)
    if vdisp_flip_yz:
        if rgb and len(vdisp_flip_yz.inputs) > 0:
            create_link(tree, rgb, vdisp_flip_yz.inputs[0])
            if len(vdisp_flip_yz.outputs) > 0:
                vdisp_output = vdisp_flip_yz.outputs[0]
            logger.debug(f"  VDM: Connected rgb -> vdisp_flip_yz -> output")

    # Apply strength multiplier through vdisp_proc
    if vdisp_proc:
        inp0, inp1, outp0 = get_mix_color_indices(vdisp_proc)

        if vdisp_output:
            create_link(tree, vdisp_output, vdisp_proc.inputs[inp0])

        # Connect vdisp_strength from channel properties
        ch_vdisp_strength = get_essential_node(tree, TREE_START).get(
            get_entity_input_name(ch, 'vdisp_strength')
        )
        if ch_vdisp_strength:
            create_link(tree, ch_vdisp_strength, vdisp_proc.inputs[inp1])
            logger.debug(f"  VDM: Connected vdisp_strength -> vdisp_proc factor")

        vdisp_output = vdisp_proc.outputs[outp0]
        logger.debug(f"  VDM: Connected vdisp input -> vdisp_proc -> output")

    return vdisp_output


def process_normal_channel(
    ctx, ch, root_ch, rgb, alpha, normal, normal_alpha,
    ch_intensity, ch_bump_distance, ch_bump_midlevel,
    layer_intensity, intensity_multiplier,
    prev_height=None, prev_height_alpha=None, next_height=None, next_height_alpha=None,
    prev_height_n=None, prev_height_s=None, prev_height_e=None, prev_height_w=None
):
    """Process NORMAL type channel specific logic.

    Connects painted texture to height_proc for bump processing, then updates
    rgb to use normal_proc/normal_map_proc outputs for the final normal vector.
    Includes smooth bump neighbor connections and transition bump handling.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        rgb: Current RGB value (painted texture).
        alpha: Current alpha value.
        normal: Normal map value.
        normal_alpha: Normal alpha value.
        ch_intensity: Channel intensity.
        ch_bump_distance: Channel bump distance.
        ch_bump_midlevel: Channel bump midlevel.
        layer_intensity: Layer intensity node.
        intensity_multiplier: Intensity multiplier.
        prev_height: Previous layer height output.
        prev_height_alpha: Previous layer height alpha.
        next_height: Next height output socket.
        next_height_alpha: Next height alpha output socket.
        prev_height_n/s/e/w: Smooth bump neighbor heights.

    Returns:
        Tuple of (rgb, alpha, normal) with rgb updated to use height/normal
        processor outputs for visible bump effects.
    """
    layer = ctx.layer
    tree = ctx.tree
    nodes = tree.nodes
    source = ctx.source

    # Get height and normal processors
    height_proc = nodes.get(ch.height_proc)
    height_blend = nodes.get(ch.height_blend)
    normal_proc = nodes.get(ch.normal_proc)
    normal_map_proc = nodes.get(ch.normal_map_proc)
    max_height_calc = nodes.get(ch.max_height_calc)
    write_height = get_write_height(ch)

    # Multiply ch_intensity with layer_intensity_value via layer_intensity node
    # This follows ucupaint pattern: ch_intensity * layer_intensity_value -> height_proc
    if layer_intensity and ctx.layer_intensity_value:
        ch_intensity = create_link(tree, ch_intensity, layer_intensity.inputs[0])[0]
        create_link(tree, ctx.layer_intensity_value, layer_intensity.inputs[1])
        logger.debug(f"  Connected ch_intensity and layer_intensity_value via layer_intensity multiply")

    # Get normal strength from TREE_START
    ch_normal_strength = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(ch, 'normal_strength')
    )

    # DEBUG: Log node status
    logger.debug(f"process_normal_channel: layer={layer.name}, type={layer.type}")
    logger.debug(f"  ch.height_proc='{ch.height_proc}' -> node={height_proc}")
    logger.debug(f"  ch.height_blend='{ch.height_blend}' -> node={height_blend}")
    logger.debug(f"  ch.normal_proc='{ch.normal_proc}' -> node={normal_proc}")
    logger.debug(f"  ch.normal_map_proc='{ch.normal_map_proc}' -> node={normal_map_proc}")
    logger.debug(f"  write_height={write_height}, normal_map_type={ch.normal_map_type}")

    if height_proc:
        logger.debug(f"  height_proc inputs: {[i.name for i in height_proc.inputs]}")
        logger.debug(f"  height_proc outputs: {[o.name for o in height_proc.outputs]}")
    if normal_proc:
        logger.debug(f"  normal_proc inputs: {[i.name for i in normal_proc.inputs]}")
        logger.debug(f"  normal_proc outputs: {[o.name for o in normal_proc.outputs]}")

    # Get context variables
    # Use the preserved pre-mask alpha for smooth-bump neighbor defaults.
    # (end_chain now carries the mask-multiplied alpha and must not be reused here.)
    if getattr(ctx, 'alpha_after_mod', None) is not None:
        alpha_after_mod = ctx.alpha_after_mod
    else:
        alpha_after_mod = ctx.end_chain if hasattr(ctx, 'end_chain') else alpha

    # Set up neighbor values for smooth bump
    (rgb_n, rgb_s, rgb_e, rgb_w,
     alpha_n, alpha_s, alpha_e, alpha_w) = setup_all_neighbor_values(
        ctx, ch, root_ch, rgb, alpha, alpha_after_mod
    )

    # Connect painted texture (rgb) to height_proc
    if height_proc:
        connect_height_proc_value_inputs(
            tree, layer, height_proc, root_ch, rgb,
            rgb_n, rgb_s, rgb_e, rgb_w
        )
        connect_height_proc_parameters(
            tree, height_proc, ch_bump_distance, ch_intensity, ch_bump_midlevel
        )

    # Handle normal input to normal_proc based on layer type
    # Also connect painted texture to normal_map_proc for NORMAL_MAP/BUMP_NORMAL_MAP modes
    connect_normal_proc_input(
        tree, nodes, layer, ch, root_ch, source, rgb, normal,
        normal_proc, normal_map_proc, height_proc
    )

    # Process transition bump or standard alpha connections
    if height_proc:
        process_transition_bump_connections(
            ctx, ch, root_ch, height_proc, max_height_calc, ch_bump_distance,
            write_height, intensity_multiplier, alpha,
            alpha_n, alpha_s, alpha_e, alpha_w
        )

    # Connect height_proc output to height_blend input
    has_parent = ctx.has_parent
    # height_alpha is for Height Blend Factor (uses "Normal Alpha" for bump modes)
    height_alpha = get_height_alpha_output(height_proc, write_height, root_ch, alpha)

    # Update alpha to use height_proc's Alpha output when write_height is false
    # This is critical for the blend Fac connection - uses "Alpha" socket for bump modes
    if height_proc and not write_height:
        # blend_alpha uses "Alpha" socket for BUMP_MAP/BUMP_NORMAL_MAP (different from height_alpha)
        alpha = get_blend_alpha_output(height_proc, write_height, root_ch, ch, alpha)
        logger.debug(f"  Updated alpha to blend_alpha for blend Fac (write_height=False)")

    if height_proc and height_blend:
        if not root_ch.enable_smooth_bump:
            connect_height_blend_standard(
                tree, ch, height_proc, height_blend, height_alpha,
                has_parent, prev_height, prev_height_alpha, write_height
            )
        else:
            connect_height_blend_smooth_bump(
                tree, ch, height_proc, height_blend, height_alpha,
                prev_height, prev_height_alpha,
                prev_height_n, prev_height_s, prev_height_e, prev_height_w,
                write_height
            )

        # Connect smooth bump height outputs
        connect_smooth_bump_height_outputs(tree, root_ch, height_proc, height_blend)

    # Connect height_blend output to normal_proc input
    if height_blend and normal_proc and 'Height' in normal_proc.inputs:
        connect_height_blend_to_normal_proc(tree, root_ch, height_blend, normal_proc)
    elif height_proc and normal_proc and 'Height' in normal_proc.inputs:
        connect_height_proc_to_normal_proc(tree, root_ch, height_proc, normal_proc)

    # Connect max_height_calc node (for bump distance tracking and normal_proc Max Height)
    connect_max_height_calc(
        tree, root_ch, layer, max_height_calc, normal_proc,
        ch_bump_distance, ch_intensity, ch_bump_midlevel
    )

    # Connect normal_proc parameters (intensity, strength, alpha, tangent/bitangent)
    connect_normal_proc_parameters(
        tree, layer, ch, root_ch, normal_proc, normal_map_proc,
        ch_intensity, ch_normal_strength, alpha, normal_alpha
    )

    # Determine final RGB output
    rgb = determine_final_rgb_output(
        tree, layer, ch, root_ch, rgb, normal_proc, normal_map_proc, write_height
    )

    # Connect height outputs to group outputs (ucupaint pattern)
    # When write_height is TRUE: height_blend output -> next_height
    # When write_height is FALSE: prev_height -> next_height (pass-through)
    if write_height and height_blend:
        if root_ch.enable_smooth_bump:
            if next_height and 'Height' in height_blend.outputs:
                create_link(tree, height_blend.outputs['Height'], next_height)
            # Also connect smooth bump neighbor heights
            next_height_n = get_essential_node(tree, TREE_END).get(root_ch.name + io_suffix["HEIGHT_N"])
            next_height_s = get_essential_node(tree, TREE_END).get(root_ch.name + io_suffix["HEIGHT_S"])
            next_height_e = get_essential_node(tree, TREE_END).get(root_ch.name + io_suffix["HEIGHT_E"])
            next_height_w = get_essential_node(tree, TREE_END).get(root_ch.name + io_suffix["HEIGHT_W"])
            if next_height_n and 'Height N' in height_blend.outputs:
                create_link(tree, height_blend.outputs['Height N'], next_height_n)
            if next_height_s and 'Height S' in height_blend.outputs:
                create_link(tree, height_blend.outputs['Height S'], next_height_s)
            if next_height_e and 'Height E' in height_blend.outputs:
                create_link(tree, height_blend.outputs['Height E'], next_height_e)
            if next_height_w and 'Height W' in height_blend.outputs:
                create_link(tree, height_blend.outputs['Height W'], next_height_w)
        else:
            # Non-smooth bump - use indexed output
            hbcol0, hbcol1, hbout = get_mix_color_indices(height_blend)
            if next_height:
                create_link(tree, height_blend.outputs[hbout], next_height)
        logger.debug(f"  Connected height_blend outputs to next_height (write_height=True)")

        # Connect height alpha outputs when write_height is true
        # When layer is in a group (has_parent), height_blend's Alpha output should go to next_height_alpha
        if next_height_alpha:
            if root_ch.enable_smooth_bump and 'Height Alpha' in height_blend.outputs:
                create_link(tree, height_blend.outputs['Height Alpha'], next_height_alpha)
            elif height_blend.type == 'GROUP' and 'Alpha' in height_blend.outputs:
                # Connect height_blend's Alpha OUTPUT to next_height_alpha (group output)
                create_link(tree, height_blend.outputs['Alpha'], next_height_alpha)
            elif height_alpha:
                # Fallback if height_blend doesn't have Alpha output
                create_link(tree, height_alpha, next_height_alpha)
    else:
        # write_height is FALSE - pass through prev to next
        if prev_height and next_height:
            create_link(tree, prev_height, next_height)
            logger.debug(f"  Pass-through: prev_height -> next_height (write_height=False)")

        if root_ch.enable_smooth_bump:
            next_height_n = get_essential_node(tree, TREE_END).get(root_ch.name + io_suffix["HEIGHT_N"])
            next_height_s = get_essential_node(tree, TREE_END).get(root_ch.name + io_suffix["HEIGHT_S"])
            next_height_e = get_essential_node(tree, TREE_END).get(root_ch.name + io_suffix["HEIGHT_E"])
            next_height_w = get_essential_node(tree, TREE_END).get(root_ch.name + io_suffix["HEIGHT_W"])
            if prev_height_n and next_height_n:
                create_link(tree, prev_height_n, next_height_n)
            if prev_height_s and next_height_s:
                create_link(tree, prev_height_s, next_height_s)
            if prev_height_e and next_height_e:
                create_link(tree, prev_height_e, next_height_e)
            if prev_height_w and next_height_w:
                create_link(tree, prev_height_w, next_height_w)

        # Pass through height alpha when write_height is false
        if prev_height_alpha and next_height_alpha:
            create_link(tree, prev_height_alpha, next_height_alpha)

    # Process VDM channel if in VECTOR_DISPLACEMENT_MAP mode
    vdisp_output = None
    if ch.normal_map_type == "VECTOR_DISPLACEMENT_MAP":
        # For VDM mode, process the painted texture through vdisp_flip_yz and vdisp_proc
        # Store original rgb (painted VDM texture) before processing
        vdisp_output = process_vdisp_channel(ctx, ch, rgb)
        logger.debug(f"  VDM mode: Processed VDM output for vdisp_blend")

    # Return modified ch_intensity so it can be used in process_intensity_node
    # This ensures layer_intensity output flows to Channel Opacity (intensity node)
    return rgb, alpha, normal, vdisp_output, ch_intensity
