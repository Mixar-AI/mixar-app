# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Node utilities for MPaint.

This module provides a unified interface for node-related utilities.
Functions are organized into submodules for better maintainability:

- node_copy_utils: Property copying functions (copy_node_props, copy_id_props, copy_fcurves)
- node_tree_utils: Tree management functions (get_node_tree_lib, remove_node, etc.)
- node_active_utils: Active node functions (get_active_node, get_active_mpaint_node, etc.)

All functions are re-exported here for backward compatibility.
"""

# Re-export all functions from submodules for backward compatibility

from .node_copy_utils import (
    copy_node_props_,
    copy_node_props,
    copy_id_props,
    copy_fcurves,
)

from .node_tree_utils import (
    is_vcol_being_used,
    create_info_nodes,
    check_duplicated_node_group,
    get_node_tree_lib,
    remove_tree_inside_tree,
    get_vertex_colors,
    get_source_vcol_name,
    remove_node,
    get_essential_node,
    clean_essential_nodes,
)

from .node_active_utils import (
    get_node_input_index,
    get_active_node,
    get_active_mpaint_node,
    is_normal_vdisp_input_connected,
    is_normal_height_input_connected,
    is_normal_input_connected,
    create_decal_empty,
)

# Define __all__ to make explicit what's exported
__all__ = [
    # From node_copy_utils
    'copy_node_props_',
    'copy_node_props',
    'copy_id_props',
    'copy_fcurves',
    # From node_tree_utils
    'is_vcol_being_used',
    'create_info_nodes',
    'check_duplicated_node_group',
    'get_node_tree_lib',
    'remove_tree_inside_tree',
    'get_vertex_colors',
    'get_source_vcol_name',
    'remove_node',
    'get_essential_node',
    'clean_essential_nodes',
    # From node_active_utils
    'get_node_input_index',
    'get_active_node',
    'get_active_mpaint_node',
    'is_normal_vdisp_input_connected',
    'is_normal_height_input_connected',
    'is_normal_input_connected',
    'create_decal_empty',
]
