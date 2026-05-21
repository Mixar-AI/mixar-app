# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer transform operators for moving and reordering paint layers.

This module serves as a coordinator that re-exports all layer transform
operators from their respective submodules.

Submodules:
- layer_transform_utils: Utility functions for layer transforms
- layer_move_ops: Layer move operators
- layer_group_ops: Layer group operations
"""

# Re-export utility functions (for backwards compatibility)
from ..helpers.layer_transform_utils import (
    finalize_layer_move,
    is_valid_parent,
    validate_layer_hierarchy,
)

# Re-export move operators
from ..helpers.layer_move_ops import MMoveLayer, MMoveLayerWithOption

# Re-export group operators
from .layer_group_ops import MMoveInOutLayerGroup, MMoveInOutLayerGroupMenu

# Aliases for internal use (underscore prefix convention)
_validate_layer_hierarchy = validate_layer_hierarchy
_is_valid_parent = is_valid_parent
_finalize_layer_move = finalize_layer_move

# Classes for registration
classes = (
    MMoveLayer,
    MMoveLayerWithOption,
    MMoveInOutLayerGroup,
    MMoveInOutLayerGroupMenu,
)


# Define __all__ for explicit exports
__all__ = [
    # Utility functions
    'validate_layer_hierarchy',
    'is_valid_parent',
    'finalize_layer_move',
    # Operators
    'MMoveLayer',
    'MMoveLayerWithOption',
    'MMoveInOutLayerGroup',
    'MMoveInOutLayerGroupMenu',
    # Classes tuple
    'classes',
]
