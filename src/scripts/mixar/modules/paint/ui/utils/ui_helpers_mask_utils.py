# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Utility functions for mask UI drawing."""

from ...core.subtree.get_subtree import get_mask_tree


def get_mask_mapping_node(mask):
    """Get the mapping node for a mask.

    Args:
        mask: YLayerMask instance

    Returns:
        Mapping node or None
    """
    tree = get_mask_tree(mask)
    if tree and mask.mapping:
        return tree.nodes.get(mask.mapping)
    return None


def get_node_drawing_functions():
    """Lazy import to avoid circular dependency with ui_helpers_layer.

    Returns:
        tuple: (draw_node_props_dynamic, draw_node_group_inputs) functions
    """
    from .ui_helpers_layer import draw_node_props_dynamic, draw_node_group_inputs
    return draw_node_props_dynamic, draw_node_group_inputs
