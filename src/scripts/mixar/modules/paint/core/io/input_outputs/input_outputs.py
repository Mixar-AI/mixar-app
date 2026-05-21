# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main entry point for layer input/output management functions.

This module serves as the central import point for all input/output related functions
for layer node trees. It re-exports functions from the following submodules:

- input_outputs_props: Property input creation functions
- input_outputs_layer_ios: Layer tree input/output management
- input_outputs_nodes: Texcoord and linear/gamma node functions

All functions are re-exported here for backward compatibility with existing imports.
"""

# Re-export property input functions
from .input_outputs_props import create_prop_input

# Re-export layer tree IO functions
from .input_outputs_layer_ios import check_layer_tree_ios

# Re-export texcoord and linear node functions
from .input_outputs_nodes import (
    check_layer_channel_linear_node,
    check_layer_image_linear_node,
    check_layer_texcoord_nodes,
    check_mask_image_linear_node,
)

# Re-export from other modules for backward compatibility
from ...node.node_active_utils import create_decal_empty

# Define __all__ for explicit public API
__all__ = [
    'create_prop_input',
    'check_layer_tree_ios',
    'check_layer_texcoord_nodes',
    'check_layer_image_linear_node',
    'check_layer_channel_linear_node',
    'check_mask_image_linear_node',
]
