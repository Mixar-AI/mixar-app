# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask operators helper module - re-exports for backward compatibility.

This module has been refactored into smaller modules for better maintainability.
All public functions are re-exported here for backward compatibility.

Modules:
    - mask_source_setup: Source setup functions (color ID, object index, edge detect, modifier)
    - mask_creation: Main add_new_mask function
    - mask_removal: Mask and channel removal functions
    - mask_type_utils: Naming, caching, and type replacement utilities
"""

# Re-export source setup functions
from .mask_source_setup import (
    setup_color_id_source,
    setup_edge_detect_source,
    setup_modifier_mask_source,
    setup_object_idx_source,
)

# Re-export mask creation function
from .mask_creation import add_new_mask

# Re-export mask removal functions
from .mask_removal import (
    remove_mask,
    remove_mask_channel,
    remove_mask_channel_nodes,
)

# Re-export mask type utility functions
from .mask_type_utils import (
    get_mask_cache_name,
    get_new_mask_name,
    is_mask_type_cacheable,
    replace_mask_type,
    update_new_mask_uv_map,
)

__all__ = [
    # Source setup
    'setup_color_id_source',
    'setup_edge_detect_source',
    'setup_modifier_mask_source',
    'setup_object_idx_source',
    # Creation
    'add_new_mask',
    # Removal
    'remove_mask',
    'remove_mask_channel',
    'remove_mask_channel_nodes',
    # Type utilities
    'get_mask_cache_name',
    'get_new_mask_name',
    'is_mask_type_cacheable',
    'replace_mask_type',
    'update_new_mask_uv_map',
]
