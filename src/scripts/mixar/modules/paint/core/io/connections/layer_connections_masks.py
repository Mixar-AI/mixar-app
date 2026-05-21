# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection mask processing - handles mask node reconnection.

This module provides mask processing functions for layer node reconnection.
It serves as the main entry point for mask processing, delegating to
specialized modules for source, vector, and channel processing.
"""

from typing import TYPE_CHECKING

from ..utils.io_utils import create_link

# Import from specialized mask modules
from ..mask.mask_source import (
    get_mask_source_index,
    get_mask_source_and_value,
    process_mask_modifiers,
    connect_mask_type_specific,
)
from ..mask.mask_vector import process_mask_vector
from ..mask.mask_channels import process_mask_root_mix, process_mask_channels

if TYPE_CHECKING:
    from .layer_connections_context import LayerConnectionContext


def process_layer_masks_ctx(ctx: "LayerConnectionContext") -> None:
    """Process all layer masks using the connection context.

    This is the context-based version that updates ctx.root_mask_val in place.

    Args:
        ctx: The LayerConnectionContext containing all needed state.
    """
    for i, mask in enumerate(ctx.layer.masks):
        _process_single_mask_ctx(ctx, mask, i)


def _process_single_mask_ctx(
    ctx: "LayerConnectionContext", mask, mask_index: int
) -> None:
    """Process a single mask's node connections using context.

    Updates ctx.root_mask_val in place.
    """
    layer = ctx.layer
    mp = ctx.mp
    tree = ctx.tree
    nodes = ctx.nodes

    # Get source output index
    mask_source_index = get_mask_source_index(mask)

    # Get mask source and value
    mask_source, mask_val = get_mask_source_and_value(
        mask, mask_source_index, tree, nodes
    )

    if mask_val is None:
        return

    # Process mask value through modifiers
    mask_val = process_mask_modifiers(mask, tree, nodes, mask_val, mask_source_index)

    # Get mask coordinate nodes
    mask_blur_vector = nodes.get(mask.blur_vector)
    mask_mapping = nodes.get(mask.mapping)
    mask_decal_process = nodes.get(mask.decal_process)
    mask_decal_alpha = nodes.get(mask.decal_alpha)
    mask_texcoord = nodes.get(mask.texcoord)

    # Process decal alpha
    if mask_decal_alpha and mask_decal_process:
        mask_val = create_link(tree, mask_val, mask_decal_alpha.inputs[0])[0]
        create_link(tree, mask_decal_process.outputs[1], mask_decal_alpha.inputs[1])

    # Layer preview mode for specific mask
    if (
        mp.layer_preview_mode
        and mp.layer_preview_mode_type == "SPECIFIC_MASK"
        and mask.active_edit == True
    ):
        if ctx.alpha_preview:
            create_link(tree, mask_val, ctx.alpha_preview)

    # Type-specific connections
    connect_mask_type_specific(mask, mask_source, tree, ctx.bump_process)

    # Process mask vector and UV neighbor
    mask_vector, mask_val_n, mask_val_s, mask_val_e, mask_val_w = process_mask_vector(
        mask, layer, tree, nodes, ctx.vector, mask_source,
        mask_blur_vector, mask_mapping, mask_decal_process, mask_texcoord,
        ctx.uv_neighbor, ctx.tangent, ctx.bitangent,
        ctx.bump_smooth_multiplier_value, mask_val
    )

    # Process mask root mix
    ctx.root_mask_val = process_mask_root_mix(
        mask, tree, nodes, ctx.root_mask_val, mask_val
    )

    # Process mask channels
    process_mask_channels(
        mask, layer, mp, tree, nodes, mask_val,
        mask_val_n, mask_val_s, mask_val_e, mask_val_w,
        ctx.uv_neighbor
    )


def process_layer_masks(
    layer, mp, tree, nodes, vector, uv_neighbor, tangent, bitangent,
    bump_process, bump_smooth_multiplier_value, alpha_preview, root_mask_val
):
    """Process all layer masks and their connections.

    Args:
        layer: The layer containing masks to process.
        mp: The MPaint data structure.
        tree: The node tree.
        nodes: The tree's nodes collection.
        vector: The texcoord vector.
        uv_neighbor: The UV neighbor node.
        tangent: The tangent node output.
        bitangent: The bitangent node output.
        bump_process: The bump process node.
        bump_smooth_multiplier_value: The bump smooth multiplier value.
        alpha_preview: The alpha preview node input.
        root_mask_val: The root mask value (modified in-place).

    Returns:
        The updated root_mask_val after processing all masks.
    """
    for i, mask in enumerate(layer.masks):
        root_mask_val = _process_single_mask(
            mask, i, layer, mp, tree, nodes, vector, uv_neighbor,
            tangent, bitangent, bump_process, bump_smooth_multiplier_value,
            alpha_preview, root_mask_val
        )

    return root_mask_val


def _process_single_mask(
    mask, mask_index, layer, mp, tree, nodes, vector, uv_neighbor,
    tangent, bitangent, bump_process, bump_smooth_multiplier_value,
    alpha_preview, root_mask_val
):
    """Process a single mask's node connections.

    Returns:
        The updated root_mask_val.
    """
    # Get source output index
    mask_source_index = get_mask_source_index(mask)

    # Get mask source and value
    mask_source, mask_val = get_mask_source_and_value(
        mask, mask_source_index, tree, nodes
    )

    if mask_val is None:
        return root_mask_val

    # Process mask value through modifiers
    mask_val = process_mask_modifiers(mask, tree, nodes, mask_val, mask_source_index)

    # Get mask coordinate nodes
    mask_blur_vector = nodes.get(mask.blur_vector)
    mask_mapping = nodes.get(mask.mapping)
    mask_decal_process = nodes.get(mask.decal_process)
    mask_decal_alpha = nodes.get(mask.decal_alpha)
    mask_texcoord = nodes.get(mask.texcoord)

    # Process decal alpha
    if mask_decal_alpha and mask_decal_process:
        mask_val = create_link(tree, mask_val, mask_decal_alpha.inputs[0])[0]
        create_link(tree, mask_decal_process.outputs[1], mask_decal_alpha.inputs[1])

    # Layer preview mode for specific mask
    if (
        mp.layer_preview_mode
        and mp.layer_preview_mode_type == "SPECIFIC_MASK"
        and mask.active_edit == True
    ):
        if alpha_preview:
            create_link(tree, mask_val, alpha_preview)

    # Type-specific connections
    connect_mask_type_specific(mask, mask_source, tree, bump_process)

    # Process mask vector and UV neighbor
    mask_vector, mask_val_n, mask_val_s, mask_val_e, mask_val_w = process_mask_vector(
        mask, layer, tree, nodes, vector, mask_source,
        mask_blur_vector, mask_mapping, mask_decal_process, mask_texcoord,
        uv_neighbor, tangent, bitangent, bump_smooth_multiplier_value, mask_val
    )

    # Process mask root mix
    root_mask_val = process_mask_root_mix(mask, tree, nodes, root_mask_val, mask_val)

    # Process mask channels
    process_mask_channels(
        mask, layer, mp, tree, nodes, mask_val,
        mask_val_n, mask_val_s, mask_val_e, mask_val_w,
        uv_neighbor
    )

    return root_mask_val
