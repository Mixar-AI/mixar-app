# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask source processing - handles mask source node retrieval and modifiers.

This module provides functions for getting mask source nodes, determining
source output indices, and processing mask modifiers.
"""

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....utils.common import get_entity_input_name
from ....utils.constants import GEOMETRY, TREE_START
from ..utils.io_utils import break_link, create_link
from ...node.node_utils import get_essential_node
from .mask_connections import reconnect_mask_internal_nodes, reconnect_mask_modifier_nodes


def get_mask_source_index(mask):
    """Get the source output index for a mask.

    Args:
        mask: The mask to get the source index for.

    Returns:
        The source output index (int or string name).
    """
    if mask.use_baked:
        return 0

    if mask.type in {"COLOR_ID", "HEMI", "OBJECT_INDEX", "EDGE_DETECT", "AO"}:
        return 0

    if mask.type == "VORONOI" and mask.voronoi_feature == "DISTANCE_TO_EDGE":
        return "Distance"
    elif mask.type == "VORONOI" and mask.voronoi_feature == "N_SPHERE_RADIUS":
        return "Radius"
    elif mask.type in {"NOISE", "VORONOI"}:
        if mask.source_input == "RGB":
            return 1
    elif mask.type == "BACKFACE":
        return "Backfacing"
    elif mask.source_input == "ALPHA":
        if mask.type == "VCOL":
            return "Alpha"
        else:
            return 1

    return 0


def get_mask_source_and_value(mask, mask_source_index, tree, nodes):
    """Get the mask source node and its output value.

    Args:
        mask: The mask to get the source for.
        mask_source_index: The output index to use.
        tree: The node tree.
        nodes: The tree's nodes collection.

    Returns:
        Tuple of (mask_source, mask_val) or (None, None) if not found.
    """
    if mask.group_node != "":
        mask_source = nodes.get(mask.group_node)
        reconnect_mask_internal_nodes(mask, mask_source_index)
        mask_val = mask_source.outputs[0] if mask_source else None
        return mask_source, mask_val

    baked_mask_source = nodes.get(mask.baked_source)
    if baked_mask_source and mask.use_baked:
        mask_source = baked_mask_source
    else:
        mask_source = nodes.get(mask.source)

    if mask.type == "BACKFACE":
        mask_val = get_essential_node(tree, GEOMETRY)[mask_source_index]
        return mask_source, mask_val

    # Safety checks
    if not mask_source:
        logger.error(f"Mask source is None for mask type {mask.type}")
        return None, None

    if isinstance(mask_source_index, int):
        if len(mask_source.outputs) <= mask_source_index:
            # This typically happens when a library node group failed to load
            # (e.g., EDGE_DETECT with missing lib.blend). The mask will be skipped
            # but the overall operation can continue.
            logger.warning(
                f"Mask source has insufficient outputs (library may not be loaded). "
                f"Source: {mask_source.name}, Outputs: {len(mask_source.outputs)}, "
                f"Requested index: {mask_source_index}, Mask type: {mask.type}. "
                f"This mask will be skipped."
            )
            return None, None
    else:
        if mask_source_index not in mask_source.outputs:
            logger.error(
                f"Mask source missing output '{mask_source_index}'. "
                f"Source: {mask_source.name}, "
                f"Available outputs: {[o.name for o in mask_source.outputs]}, "
                f"Mask type: {mask.type}"
            )
            return None, None

    mask_val = mask_source.outputs[mask_source_index]
    return mask_source, mask_val


def process_mask_modifiers(mask, tree, nodes, mask_val, mask_source_index):
    """Process mask through linear node and modifiers.

    Args:
        mask: The mask being processed.
        tree: The node tree.
        nodes: The tree's nodes collection.
        mask_val: The current mask value.
        mask_source_index: The source output index.

    Returns:
        The processed mask value after modifiers.
    """
    if mask.group_node != "":
        return mask_val

    mask_linear = nodes.get(mask.linear)
    mask_separate_color_channels = nodes.get(mask.separate_color_channels)

    # Process color channel separation
    if mask.source_input in {"R", "G", "B"} and mask_separate_color_channels:
        separate_outputs = create_link(
            tree, mask_val, mask_separate_color_channels.inputs[0]
        )
        if mask.source_input == "R":
            mask_val = separate_outputs[0]
        elif mask.source_input == "G":
            mask_val = separate_outputs[1]
        elif mask.source_input == "B":
            mask_val = separate_outputs[2]

    if mask_linear:
        mask_val = create_link(tree, mask_val, mask_linear.inputs[0])[0]

    for mod in mask.modifiers:
        mask_val = reconnect_mask_modifier_nodes(tree, mod, mask_val)

    return mask_val


def connect_mask_type_specific(mask, mask_source, tree, bump_process):
    """Connect type-specific mask inputs.

    Args:
        mask: The mask being processed.
        mask_source: The mask source node.
        tree: The node tree.
        bump_process: The bump process node.
    """
    if not mask_source:
        return

    if mask.type == "COLOR_ID":
        color_id_val = get_essential_node(tree, TREE_START).get(
            get_entity_input_name(mask, "color_id")
        )
        if color_id_val and "Color ID" in mask_source.inputs:
            create_link(tree, color_id_val, mask_source.inputs["Color ID"])

    elif mask.type == "EDGE_DETECT":
        edge_detect_radius_val = get_essential_node(tree, TREE_START).get(
            get_entity_input_name(mask, "edge_detect_radius")
        )
        if edge_detect_radius_val and "Radius" in mask_source.inputs:
            create_link(tree, edge_detect_radius_val, mask_source.inputs["Radius"])

    elif mask.type == "AO":
        ao_distance_val = get_essential_node(tree, TREE_START).get(
            get_entity_input_name(mask, "ao_distance")
        )
        if ao_distance_val and "Distance" in mask_source.inputs:
            create_link(tree, ao_distance_val, mask_source.inputs["Distance"])

    # Hemi-related normal connection
    if mask.type in {"HEMI", "EDGE_DETECT", "AO"} and not mask.use_baked:
        if mask.hemi_use_prev_normal and bump_process:
            create_link(tree, bump_process.outputs["Normal"], mask_source.inputs["Normal"])
        elif "Normal" in mask_source.inputs:
            create_link(
                tree,
                get_essential_node(tree, GEOMETRY)["Normal"],
                mask_source.inputs["Normal"],
            )
