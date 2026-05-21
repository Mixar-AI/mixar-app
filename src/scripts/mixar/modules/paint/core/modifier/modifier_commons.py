# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modifier common utilities - re-exports for backward compatibility.

This module re-exports all modifier-related functions from their respective
submodules to maintain backward compatibility with existing code that imports
from modifier_commons.

The functionality has been split into:
- modifier_channel.py: Channel type detection utilities
- modifier_props.py: Property save/load utilities
- modifier_nodes.py: Node management utilities
"""

# Re-export channel utilities
from .modifier_channel import get_modifier_channel_type

# Re-export property save/load utilities
from .modifier_props import (
    save_rgb2i_props,
    load_rgb2i_anim_props,
    save_huesat_props,
    load_huesat_anim_props,
    save_brightcon_props,
    load_brightcon_anim_props,
    save_math_props,
    load_math_anim_props,
)

# Re-export node management utilities
from .modifier_nodes import (
    check_modifier_nodes,
    delete_modifier_nodes,
)

# Define __all__ for explicit public API
__all__ = [
    # Channel utilities
    'get_modifier_channel_type',
    # Property save/load utilities
    'save_rgb2i_props',
    'load_rgb2i_anim_props',
    'save_huesat_props',
    'load_huesat_anim_props',
    'save_brightcon_props',
    'load_brightcon_anim_props',
    'save_math_props',
    'load_math_anim_props',
    # Node management utilities
    'check_modifier_nodes',
    'delete_modifier_nodes',
]
