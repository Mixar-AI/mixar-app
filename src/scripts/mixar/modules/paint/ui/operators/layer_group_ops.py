# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer group operators for Mixar layers system.

This module aggregates all layer group-related operators from modular files:
- layer_menu_ops: Layer operations popup menu
- layer_group_membership_ops: Add/move/remove layers to/from groups

The classes tuple combines all operators for registration.
"""

# Import operators from modular files
from .layer_menu_ops import (
    LAYERS_OT_SelectedLayersMenu,
)

from .layer_group_membership_ops import (
    LAYERS_OT_MoveSelectedToGroup,
    LAYERS_OT_AddLayersToGroup,
    LAYERS_OT_RemoveFromGroup,
    get_available_groups,
)


# Only register classes defined in membership_ops
# LAYERS_OT_SelectedLayersMenu is registered by layer_menu_ops.py to avoid double registration
classes = (
    LAYERS_OT_MoveSelectedToGroup,
    LAYERS_OT_AddLayersToGroup,
    LAYERS_OT_RemoveFromGroup,
)


# Re-export for backward compatibility
__all__ = [
    'LAYERS_OT_SelectedLayersMenu',
    'LAYERS_OT_MoveSelectedToGroup',
    'LAYERS_OT_AddLayersToGroup',
    'LAYERS_OT_RemoveFromGroup',
    'get_available_groups',
]
