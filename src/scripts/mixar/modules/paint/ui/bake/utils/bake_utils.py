# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Utility functions for bake operations.

This module re-exports functions from split modules for backward compatibility.
"""

# Re-export constants
from .bake_constants import (
    rgba_items,
    normal_type_items,
)

# Re-export update handlers
from .bake_update_handlers import (
    update_enable_bake_to_vcol,
    update_subdiv_max_polys,
    update_subdiv_global_dicing,
    update_active_bake_target_index,
    update_use_baked,
)

# Re-export baked outside node functions
from ..channel.bake_outside_nodes import (
    update_enable_baked_outside,
)

# Export all public names for backward compatibility
__all__ = [
    # Constants
    "rgba_items",
    "normal_type_items",
    # Update handlers
    "update_enable_bake_to_vcol",
    "update_subdiv_max_polys",
    "update_subdiv_global_dicing",
    "update_active_bake_target_index",
    "update_use_baked",
    # Baked outside nodes
    "update_enable_baked_outside",
]
