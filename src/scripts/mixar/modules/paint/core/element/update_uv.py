# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
UV update and management operations.

This module provides functions for managing UV layers, including temporary UV creation,
UV transformations, UV layer reordering, and UV node management.

All functions are re-exported from helper modules in uv_helpers/ for backward compatibility.
"""

# Re-export all functions from helper modules for backward compatibility
from .uv_helpers.uv_mirror import set_uv_mirror_offsets
from .uv_helpers.uv_temp import remove_temp_uv, refresh_temp_uv
from .uv_helpers.uv_layers import move_uv_to_bottom, move_uv, set_active_uv_layer
from .uv_helpers.uv_nodes import remove_uv_nodes
from .uv_helpers.uv_resolution import set_uv_neighbor_resolution

__all__ = [
    'set_uv_neighbor_resolution',
    'set_uv_mirror_offsets',
    'remove_temp_uv',
    'refresh_temp_uv',
    'move_uv_to_bottom',
    'move_uv',
    'set_active_uv_layer',
    'remove_uv_nodes',
]
