# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask vector processing - handles mask vector and UV neighbor connections.

This module provides functions for processing mask vectors, UV neighbor
connections, tangent/bitangent connections, and direction source handling.
"""

from ....utils.common import get_entity_input_name
from ....utils.constants import TREE_START, io_names, io_suffix
from ..utils.io_utils import break_link, create_link
from ...node.node_utils import get_essential_node


def process_mask_vector(
    mask, layer, tree, nodes, vector, mask_source,
    mask_blur_vector, mask_mapping, mask_decal_process, mask_texcoord,
    uv_neighbor, tangent, bitangent, bump_smooth_multiplier_value, mask_val
):
    """Process mask vector and UV neighbor connections.

    Args:
        mask: The mask being processed.
        layer: The layer containing the mask.
        tree: The node tree.
        nodes: The tree's nodes collection.
        vector: The texcoord vector.
        mask_source: The mask source node.
        mask_blur_vector: The mask blur vector node.
        mask_mapping: The mask mapping node.
        mask_decal_process: The mask decal process node.
        mask_texcoord: The mask texcoord node.
        uv_neighbor: The UV neighbor node.
        tangent: The tangent node output.
        bitangent: The bitangent node output.
        bump_smooth_multiplier_value: The bump smooth multiplier value.
        mask_val: The current mask value.

    Returns:
        Tuple of (mask_vector, mask_val_n, mask_val_s, mask_val_e, mask_val_w)
    """
    mask_val_n = mask_val_s = mask_val_e = mask_val_w = None
    mask_vector = None

    mask_uv_name = (
        mask.uv_name
        if not mask.use_baked or mask.baked_uv_name == ""
        else mask.baked_uv_name
    )

    # Determine if we need to process vector
    needs_vector = mask.use_baked or mask.type not in {
        "VCOL", "HEMI", "OBJECT_INDEX", "COLOR_ID", "BACKFACE", "EDGE_DETECT", "AO"
    }

    if needs_vector:
        mask_vector = _get_mask_vector(
            mask, mask_uv_name, tree, vector, mask_texcoord, mask_decal_process
        )

        if mask_vector:
            mask_vector = _apply_mask_vector_transforms(
                mask, tree, nodes, mask_vector, mask_source,
                mask_blur_vector, mask_mapping
            )

    # Process UV neighbor
    mask_uv_neighbor = (
        nodes.get(mask.uv_neighbor)
        if mask.texcoord_type != "Layer"
        else uv_neighbor
    )

    if mask_uv_neighbor:
        mask_val_n, mask_val_s, mask_val_e, mask_val_w = _process_mask_uv_neighbor(
            mask, layer, tree, nodes, mask_vector, mask_val,
            mask_uv_neighbor, mask_decal_process, uv_neighbor,
            tangent, bitangent, bump_smooth_multiplier_value, mask_uv_name
        )

    return mask_vector, mask_val_n, mask_val_s, mask_val_e, mask_val_w


def _get_mask_vector(mask, mask_uv_name, tree, vector, mask_texcoord, mask_decal_process):
    """Get the initial mask vector based on texcoord type.

    Args:
        mask: The mask being processed.
        mask_uv_name: The UV name to use.
        tree: The node tree.
        vector: The texcoord vector.
        mask_texcoord: The mask texcoord node.
        mask_decal_process: The mask decal process node.

    Returns:
        The mask vector or None.
    """
    if mask.use_baked or mask.texcoord_type == "UV":
        return get_essential_node(tree, TREE_START).get(
            mask_uv_name + io_suffix["UV"]
        )
    elif mask.texcoord_type == "Decal":
        if mask_texcoord:
            mask_vec = mask_texcoord.outputs["Object"]
            if mask_decal_process:
                layer_decal_distance = get_essential_node(tree, TREE_START).get(
                    get_entity_input_name(mask, "decal_distance_value")
                )
                mask_vec = create_link(tree, mask_vec, mask_decal_process.inputs[0])[0]
                if layer_decal_distance:
                    create_link(tree, layer_decal_distance, mask_decal_process.inputs[1])
            return mask_vec
    elif mask.texcoord_type == "Layer":
        return vector
    else:
        return get_essential_node(tree, TREE_START).get(
            io_names[mask.texcoord_type]
        )
    return None


def _apply_mask_vector_transforms(
    mask, tree, nodes, mask_vector, mask_source,
    mask_blur_vector, mask_mapping
):
    """Apply transforms to mask vector (baked mapping, blur, mapping).

    Args:
        mask: The mask being processed.
        tree: The node tree.
        nodes: The tree's nodes collection.
        mask_vector: The current mask vector.
        mask_source: The mask source node.
        mask_blur_vector: The mask blur vector node.
        mask_mapping: The mask mapping node.

    Returns:
        The transformed mask vector.
    """
    if mask.use_baked:
        mask_baked_mapping = nodes.get(mask.baked_mapping)
        if mask_baked_mapping:
            mask_vector = create_link(tree, mask_vector, mask_baked_mapping.inputs[0])[0]
    elif mask.texcoord_type != "Layer":
        mask_blur_factor = get_essential_node(tree, TREE_START).get(
            get_entity_input_name(mask, "blur_vector_factor")
        )
        if mask_blur_factor and mask_blur_vector:
            create_link(tree, mask_blur_factor, mask_blur_vector.inputs[0])

        if mask_blur_vector:
            mask_vector = create_link(tree, mask_vector, mask_blur_vector.inputs[1])[0]

        if mask_mapping and mask.texcoord_type != "Decal":
            mask_vector = create_link(tree, mask_vector, mask_mapping.inputs[0])[0]

    if mask_source and mask_vector:
        create_link(tree, mask_vector, mask_source.inputs[0])

    # Uniform scale
    uniform_scale_value = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(mask, "uniform_scale_value")
    )
    if uniform_scale_value and mask_mapping:
        if mask.enable_uniform_scale:
            create_link(tree, uniform_scale_value, mask_mapping.inputs[3])
        else:
            break_link(tree, uniform_scale_value, mask_mapping.inputs[3])

    return mask_vector


def _process_mask_uv_neighbor(
    mask, layer, tree, nodes, mask_vector, mask_val,
    mask_uv_neighbor, mask_decal_process, uv_neighbor,
    tangent, bitangent, bump_smooth_multiplier_value, mask_uv_name
):
    """Process mask UV neighbor connections.

    Args:
        mask: The mask being processed.
        layer: The layer containing the mask.
        tree: The node tree.
        nodes: The tree's nodes collection.
        mask_vector: The mask vector.
        mask_val: The current mask value.
        mask_uv_neighbor: The mask UV neighbor node.
        mask_decal_process: The mask decal process node.
        uv_neighbor: The layer UV neighbor node.
        tangent: The tangent node output.
        bitangent: The bitangent node output.
        bump_smooth_multiplier_value: The bump smooth multiplier value.
        mask_uv_name: The UV name for the mask.

    Returns:
        Tuple of (mask_val_n, mask_val_s, mask_val_e, mask_val_w)
    """
    mask_val_n = mask_val_s = mask_val_e = mask_val_w = None

    # Connect mask value or vector to UV neighbor input
    if not mask.use_baked and mask.type in {
        "VCOL", "HEMI", "OBJECT_INDEX", "COLOR_ID", "BACKFACE", "EDGE_DETECT", "AO"
    }:
        create_link(tree, mask_val, mask_uv_neighbor.inputs[0])
    else:
        if mask_vector and mask.texcoord_type != "Layer":
            create_link(tree, mask_vector, mask_uv_neighbor.inputs[0])

        # Get direction sources and connect
        mask_val_n, mask_val_s, mask_val_e, mask_val_w = _connect_mask_direction_sources(
            mask, tree, nodes, mask_uv_neighbor, mask_decal_process
        )

    # Connect tangent/bitangent and multiplier
    if mask.texcoord_type != "Layer":
        _connect_mask_tangent_bitangent(
            mask, tree, mask_uv_neighbor, tangent, bitangent,
            bump_smooth_multiplier_value, mask_uv_name
        )

    return mask_val_n, mask_val_s, mask_val_e, mask_val_w


def _connect_mask_direction_sources(mask, tree, nodes, mask_uv_neighbor, mask_decal_process):
    """Connect mask direction source nodes (N, S, E, W).

    Args:
        mask: The mask being processed.
        tree: The node tree.
        nodes: The tree's nodes collection.
        mask_uv_neighbor: The mask UV neighbor node.
        mask_decal_process: The mask decal process node.

    Returns:
        Tuple of (mask_val_n, mask_val_s, mask_val_e, mask_val_w)
    """
    mask_val_n = mask_val_s = mask_val_e = mask_val_w = None

    mask_source_n = nodes.get(mask.source_n)
    mask_source_s = nodes.get(mask.source_s)
    mask_source_e = nodes.get(mask.source_e)
    mask_source_w = nodes.get(mask.source_w)

    if mask_source_n:
        mask_val_n = create_link(tree, mask_uv_neighbor.outputs["n"], mask_source_n.inputs[0])[0]
    if mask_source_s:
        mask_val_s = create_link(tree, mask_uv_neighbor.outputs["s"], mask_source_s.inputs[0])[0]
    if mask_source_e:
        mask_val_e = create_link(tree, mask_uv_neighbor.outputs["e"], mask_source_e.inputs[0])[0]
    if mask_source_w:
        mask_val_w = create_link(tree, mask_uv_neighbor.outputs["w"], mask_source_w.inputs[0])[0]

    # Process decal alpha for directions
    if mask_decal_process:
        mask_val_n, mask_val_s, mask_val_e, mask_val_w = _process_decal_direction_alphas(
            mask, tree, nodes, mask_decal_process,
            mask_val_n, mask_val_s, mask_val_e, mask_val_w
        )

    return mask_val_n, mask_val_s, mask_val_e, mask_val_w


def _process_decal_direction_alphas(
    mask, tree, nodes, mask_decal_process,
    mask_val_n, mask_val_s, mask_val_e, mask_val_w
):
    """Process decal alpha for direction mask values.

    Args:
        mask: The mask being processed.
        tree: The node tree.
        nodes: The tree's nodes collection.
        mask_decal_process: The mask decal process node.
        mask_val_n: North direction mask value.
        mask_val_s: South direction mask value.
        mask_val_e: East direction mask value.
        mask_val_w: West direction mask value.

    Returns:
        Tuple of updated (mask_val_n, mask_val_s, mask_val_e, mask_val_w)
    """
    directions = [
        ("decal_alpha_n", mask_val_n),
        ("decal_alpha_s", mask_val_s),
        ("decal_alpha_e", mask_val_e),
        ("decal_alpha_w", mask_val_w),
    ]

    results = []
    for attr_name, mask_val_dir in directions:
        decal_alpha_dir = nodes.get(getattr(mask, attr_name))
        if decal_alpha_dir and mask_val_dir:
            mask_val_dir = create_link(tree, mask_val_dir, decal_alpha_dir.inputs[0])[0]
            create_link(tree, mask_decal_process.outputs[1], decal_alpha_dir.inputs[1])
        results.append(mask_val_dir)

    return tuple(results)


def _connect_mask_tangent_bitangent(
    mask, tree, mask_uv_neighbor, tangent, bitangent,
    bump_smooth_multiplier_value, mask_uv_name
):
    """Connect tangent and bitangent to mask UV neighbor.

    Args:
        mask: The mask being processed.
        tree: The node tree.
        mask_uv_neighbor: The mask UV neighbor node.
        tangent: The tangent node output.
        bitangent: The bitangent node output.
        bump_smooth_multiplier_value: The bump smooth multiplier value.
        mask_uv_name: The UV name for the mask.
    """
    # UV Neighbor multiplier
    if bump_smooth_multiplier_value and "Multiplier" in mask_uv_neighbor.inputs:
        create_link(tree, bump_smooth_multiplier_value, mask_uv_neighbor.inputs["Multiplier"])

    # Mask tangent
    mask_tangent = get_essential_node(tree, TREE_START).get(
        mask_uv_name + io_suffix["TANGENT"]
    )
    mask_bitangent = get_essential_node(tree, TREE_START).get(
        mask_uv_name + io_suffix["BITANGENT"]
    )

    if "Tangent" in mask_uv_neighbor.inputs:
        if tangent:
            create_link(tree, tangent, mask_uv_neighbor.inputs["Tangent"])
        if bitangent:
            create_link(tree, bitangent, mask_uv_neighbor.inputs["Bitangent"])

    if "Mask Tangent" in mask_uv_neighbor.inputs:
        if mask_tangent:
            create_link(tree, mask_tangent, mask_uv_neighbor.inputs["Mask Tangent"])
        if mask_bitangent:
            create_link(tree, mask_bitangent, mask_uv_neighbor.inputs["Mask Bitangent"])

    if "Entity Tangent" in mask_uv_neighbor.inputs:
        if mask_tangent:
            create_link(tree, mask_tangent, mask_uv_neighbor.inputs["Entity Tangent"])
        if mask_bitangent:
            create_link(tree, mask_bitangent, mask_uv_neighbor.inputs["Entity Bitangent"])
