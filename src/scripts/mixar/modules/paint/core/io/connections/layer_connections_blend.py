# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection blend processing - handles blend node connections.

This module provides blend and output node processing functions for layer
node reconnection. Extracted from the main reconnect_layer_nodes function.
"""

from typing import TYPE_CHECKING, Any

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....utils.common import get_mix_color_indices


from ....utils.constants import (
    TREE_END,
    TREE_START,
    LAYER_VIEWER,
    io_suffix,
)
from ..utils.io_utils import create_link
from ...node.node_utils import get_essential_node

if TYPE_CHECKING:
    from .layer_connections_context import LayerConnectionContext


def process_blend_node(
    ctx: "LayerConnectionContext",
    ch,
    root_ch,
    blend,
    rgb: Any,
    alpha: Any,
    normal: Any,
    normal_alpha: Any,
    prev_rgb: Any,
    prev_alpha: Any,
    next_rgb: Any,
    next_alpha: Any,
    bg_alpha: Any,
    normal_proc,
) -> None:
    """Process blend node connections.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        blend: The blend node.
        rgb: Current RGB value.
        alpha: Current alpha value.
        normal: Normal map value.
        normal_alpha: Normal alpha value.
        prev_rgb: Previous RGB input.
        prev_alpha: Previous alpha input.
        next_rgb: Next RGB output.
        next_alpha: Next alpha output.
        bg_alpha: Background alpha.
        normal_proc: Normal processor node.
    """
    layer = ctx.layer
    tree = ctx.tree
    has_parent = ctx.has_parent

    # Determine blend type
    if layer.type == "BACKGROUND":
        blend_type = "MIX"
    else:
        if root_ch.type == "NORMAL":
            blend_type = ch.normal_blend_type
        else:
            blend_type = ch.blend_type

    if blend:
        bcol0, bcol1, bout = get_mix_color_indices(blend)

        # Pass rgb to blend
        if layer.type == "GROUP" and root_ch.type == "NORMAL" and not normal_proc:
            if normal:
                create_link(tree, normal, blend.inputs[bcol1])
            else:
                logger.debug("Normal socket is None, skipping blend connection")
        else:
            if rgb:
                create_link(tree, rgb, blend.inputs[bcol1])
            else:
                logger.debug("RGB socket is None, skipping blend connection")

        if (
            (blend_type in {"MIX", "COMPARE"} and (has_parent or root_ch.enable_alpha))
            or (blend_type == "OVERLAY" and has_parent and root_ch.type == "NORMAL")
        ):
            # Use direct index access like ucupaint does
            if prev_rgb:
                create_link(tree, prev_rgb, blend.inputs[0])
            if prev_alpha:
                create_link(tree, prev_alpha, blend.inputs[1])

            # Connect alpha (Channel Opacity output) to blend Fac input
            if alpha:
                create_link(tree, alpha, blend.inputs[3])
                logger.debug(f"  Blend: Connected alpha to inputs[3] (Fac) - has_parent={has_parent}")
            else:
                logger.warning(f"  Blend: alpha is None, cannot connect to inputs[3]")

            if bg_alpha and len(blend.inputs) > 4:
                create_link(tree, bg_alpha, blend.inputs[4])
        else:
            # Connect alpha (Channel Opacity output) to blend Fac input (inputs[0])
            # For GROUP NORMAL without normal_proc, use normal_alpha from context
            # (which should already be updated through process_intensity_node)
            fac_socket = alpha
            if (
                layer.type == "GROUP"
                and root_ch.type == "NORMAL"
                and not normal_proc
                and normal_alpha
            ):
                fac_socket = normal_alpha
                logger.debug(f"  Blend: Using normal_alpha for Fac connection - GROUP NORMAL")

            if fac_socket:
                # Try to use named 'Fac' input for GROUP nodes, fallback to inputs[0]
                if blend.type == "GROUP" and 'Fac' in blend.inputs:
                    create_link(tree, fac_socket, blend.inputs['Fac'])
                    logger.debug(f"  Blend: Connected to named 'Fac' input - layer={layer.name}")
                else:
                    create_link(tree, fac_socket, blend.inputs[0])
                    logger.debug(f"  Blend: Connected to inputs[0] (Fac) - layer={layer.name}")
            else:
                logger.warning(f"  Blend: fac_socket (alpha/normal_alpha) is None, cannot connect to Fac")

            if prev_rgb:
                create_link(tree, prev_rgb, blend.inputs[bcol0])

        # Connect tangent/bitangent if OVERLAY blend is used (ucupaint pattern)
        if root_ch.type == "NORMAL" and ch.normal_blend_type == "OVERLAY":
            layer = ctx.layer
            uv_name = getattr(layer, 'uv_name', None) or getattr(root_ch, 'main_uv', None)
            if uv_name:
                tangent = get_essential_node(tree, TREE_START).get(uv_name + io_suffix['TANGENT'])
                bitangent = get_essential_node(tree, TREE_START).get(uv_name + io_suffix['BITANGENT'])
                if tangent and 'Tangent' in blend.inputs:
                    create_link(tree, tangent, blend.inputs['Tangent'])
                if bitangent and 'Bitangent' in blend.inputs:
                    create_link(tree, bitangent, blend.inputs['Bitangent'])

        if next_rgb:
            create_link(tree, blend.outputs[bout], next_rgb)

    elif prev_rgb and next_rgb:
        create_link(tree, prev_rgb, next_rgb)


def process_vdisp_blend(
    ctx: "LayerConnectionContext",
    ch,
    root_ch,
    vdisp_blend,
    rgb: Any,
    alpha: Any,
    vdisp_alpha: Any,
    group_vdisp: Any,
    prev_vdisp: Any,
    next_vdisp: Any,
    prev_vdisp_alpha: Any,
    next_vdisp_alpha: Any,
    ch_intensity: Any,
) -> None:
    """Process vector displacement blend node.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        vdisp_blend: The vdisp blend node.
        rgb: Current RGB value.
        alpha: Current alpha value.
        vdisp_alpha: Vector displacement alpha.
        group_vdisp: Group vector displacement.
        prev_vdisp: Previous vdisp input.
        next_vdisp: Next vdisp output.
        prev_vdisp_alpha: Previous vdisp alpha.
        next_vdisp_alpha: Next vdisp alpha output.
        ch_intensity: Channel intensity value.
    """
    layer = ctx.layer
    tree = ctx.tree

    bcol0, bcol1, bout = get_mix_color_indices(vdisp_blend)

    if prev_vdisp:
        create_link(tree, prev_vdisp, vdisp_blend.inputs[bcol0])

    vdisp = rgb
    if vdisp_alpha is None:
        vdisp_alpha = alpha

    if layer.type == "GROUP":
        if group_vdisp:
            vdisp = group_vdisp

        vdisp_intensity = tree.nodes.get(ch.vdisp_intensity)

        if vdisp_intensity and ch_intensity:
            vdisp_alpha = create_link(tree, vdisp_alpha, vdisp_intensity.inputs[0])[0]
            create_link(tree, ch_intensity, vdisp_intensity.inputs[1])

    if vdisp:
        create_link(tree, vdisp, vdisp_blend.inputs[bcol1])

    if next_vdisp:
        create_link(tree, vdisp_blend.outputs[bout], next_vdisp)

    if vdisp_alpha:
        if "Alpha2" in vdisp_blend.inputs:
            create_link(tree, vdisp_alpha, vdisp_blend.inputs["Alpha2"])
        else:
            create_link(tree, vdisp_alpha, vdisp_blend.inputs[0])

    if prev_vdisp_alpha and "Alpha1" in vdisp_blend.inputs:
        create_link(tree, prev_vdisp_alpha, vdisp_blend.inputs["Alpha1"])

    if next_vdisp_alpha:
        if "Value" in vdisp_blend.outputs:
            create_link(tree, vdisp_blend.outputs["Value"], next_vdisp_alpha)
        elif "Alpha" in vdisp_blend.outputs:
            create_link(tree, vdisp_blend.outputs["Alpha"], next_vdisp_alpha)


def process_alpha_output(
    ctx: "LayerConnectionContext",
    ch,
    root_ch,
    blend,
    prev_alpha: Any,
    next_alpha: Any,
) -> None:
    """Process alpha output connections.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        blend: The blend node.
        prev_alpha: Previous alpha input.
        next_alpha: Next alpha output.
    """
    layer = ctx.layer
    tree = ctx.tree
    has_parent = ctx.has_parent

    # Determine blend type
    if layer.type == "BACKGROUND":
        blend_type = "MIX"
    else:
        if root_ch.type == "NORMAL":
            blend_type = ch.normal_blend_type
        else:
            blend_type = ch.blend_type

    if next_alpha:
        if not blend or (
            (blend_type != "MIX" and (has_parent or root_ch.enable_alpha))
            and not (blend_type == "OVERLAY" and has_parent and root_ch.type == "NORMAL")
        ):
            if prev_alpha and next_alpha:
                create_link(tree, prev_alpha, next_alpha)
        else:
            if blend and next_alpha:
                create_link(tree, blend.outputs[1], next_alpha)


def process_layer_preview(
    ctx: "LayerConnectionContext",
    ch,
    root_ch,
    i: int,
    rgb: Any,
    alpha: Any,
    normal_proc,
) -> None:
    """Process layer preview mode.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        i: Channel index.
        rgb: Current RGB value.
        alpha: Current alpha value.
        normal_proc: Normal processor node.
    """
    layer = ctx.layer
    mp = ctx.mp
    tree = ctx.tree
    source = ctx.source

    if mp.layer_preview_mode_type == "SPECIFIC_MASK":
        active_found = False

        for mask in layer.masks:
            if mask.active_edit:
                active_found = True
                break

        if not active_found and ctx.alpha_preview and source:
            create_link(tree, source.outputs[0], ctx.alpha_preview)

    elif root_ch == mp.channels[mp.active_channel_index]:
        col_preview = get_essential_node(tree, TREE_END).get(LAYER_VIEWER)
        if col_preview:
            if root_ch.type == "NORMAL" and normal_proc:
                create_link(tree, normal_proc.outputs[0], col_preview)
            else:
                create_link(tree, rgb, col_preview)
        if ctx.alpha_preview and mp.layer_preview_mode_type != "SPECIFIC_MASK":
            create_link(tree, alpha, ctx.alpha_preview)
