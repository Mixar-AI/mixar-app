# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Subtree operations for layers, channels, and masks.

This module re-exports all subtree-related functions from specialized modules
for backward compatibility. The functionality has been split into:

- tree_operations: Tree retrieval functions (get_tree, get_source_tree, etc.)
- layer_hierarchy: Layer hierarchy functions (children, parents, neighbors)
- height_calculations: Height calculation functions for displacement/bump
"""

# Tree operations
from .tree_operations import (
    get_tree,
    get_source_tree,
    get_mod_tree,
    get_mask_tree,
    get_channel_source_tree,
)

# Layer hierarchy operations
from .layer_hierarchy import (
    get_list_of_direct_child_ids,
    get_list_of_direct_children,
    get_list_of_all_children_and_child_ids,
    get_list_of_parent_ids,
    get_last_chained_up_layer_ids,
    get_last_child_idx,
    get_upper_neighbor,
    get_lower_neighbor,
    get_parent_dict,
    get_index_dict,
    get_parent,
)

# Height calculation operations
from .height_calculations import (
    get_max_child_height,
    get_transition_disp_delta,
    get_max_height_from_list_of_layers,
    get_displacement_max_height,
    get_layer_channel_max_height,
    has_channel_children,
)

# Define __all__ for explicit exports
__all__ = [
    # Tree operations
    "get_tree",
    "get_source_tree",
    "get_mod_tree",
    "get_mask_tree",
    "get_channel_source_tree",
    # Layer hierarchy operations
    "get_list_of_direct_child_ids",
    "get_list_of_direct_children",
    "get_list_of_all_children_and_child_ids",
    "get_list_of_parent_ids",
    "get_last_chained_up_layer_ids",
    "get_last_child_idx",
    "get_upper_neighbor",
    "get_lower_neighbor",
    "get_parent_dict",
    "get_index_dict",
    "get_parent",
    # Height calculation operations
    "get_max_child_height",
    "get_transition_disp_delta",
    "get_max_height_from_list_of_layers",
    "get_displacement_max_height",
    "get_layer_channel_max_height",
    "has_channel_children",
]
