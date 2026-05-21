# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer operation helpers: search, remove, replace operations.

This module re-exports all functions from the following helper modules for
backward compatibility:
- layer_search_helpers: search_for_images, search_for_image_node
- layer_ui_draw_helpers: draw_move_up_in_layer_group, draw_move_down_in_layer_group, draw_remove_group
- layer_removal_helpers: remove_layer
- layer_type_helpers: replace_layer_type
"""

# Re-export search functions
from .layer_search_helpers import (
    search_for_images,
    search_for_image_node,
)

# Re-export UI draw functions
from .layer_ui_draw_helpers import (
    draw_move_up_in_layer_group,
    draw_move_down_in_layer_group,
    draw_remove_group,
)

# Re-export layer removal functions
from .layer_removal_helpers import (
    remove_layer,
)

# Re-export layer type replacement functions
from .layer_type_helpers import (
    replace_layer_type,
)

# Define __all__ for explicit public API
__all__ = [
    "search_for_images",
    "search_for_image_node",
    "draw_move_up_in_layer_group",
    "draw_move_down_in_layer_group",
    "draw_remove_group",
    "remove_layer",
    "replace_layer_type",
]
