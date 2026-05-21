# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bake operators helper - Wrapper for split bake helper modules

This file maintains backward compatibility by re-exporting all functions
from the split modules. All functions have been organized into logical groups:

- bake_subdivision.py - Subdivision and displacement setup
- bake_layer_modifiers.py - Layer modifier management
- bake_node_utils.py - Node utility functions
- bake_property_callbacks.py - Property update callbacks
- bake_uv_transfer.py - UV transfer operations
- bake_channel_core.py - Channel baking logic
- bake_to_entity.py - Main entity baking function

Also re-exports core functions that were previously imported here:
- check_displacement_node from core.layer.check_channels
"""

# Core re-exports (functions from core that were previously imported here)
from ....core.layer.check_channels import check_displacement_node

# Subdivision functions
from .bake_subdivision import (
    check_subdiv_setup,
    get_objs_size_proportions,
    recover_subsurf_levels,
    remember_subsurf_levels,
    setup_subdiv_to_max_polys,
    update_enable_subdiv_setup,
    update_subdiv_setup,
)

# Layer modifier functions
from ..layer.bake_layer_modifiers import (
    recover_layer_modifiers_and_transforms,
    remember_and_disable_layer_modifiers_and_transforms,
    remove_layer_modifiers_and_transforms,
)

# Node utility functions
from .bake_node_utils import connect_to_original_node, copy_default_value

# Property callback functions
from .bake_property_callbacks import (
    bake_vcol_channel_items,
    get_resize_image_entity_and_image,
    merge_channel_items,
    udim_tilenum_items,
    update_bake_channel_uv_map,
    update_resize_image_tile_number,
)

# UV transfer functions
from .bake_uv_transfer import (
    get_entities_to_transfer,
    set_entities_which_using_the_same_image_or_segment,
    transfer_uv,
)

# Channel baking functions
from ..channel.bake_channel_core import (
    bake_channel,
    disable_temp_bake,
    rebake_baked_images,
    temp_bake,
)

# Main entity baking function
from ..entity.bake_to_entity import bake_to_entity

# Maintain __all__ for explicit exports
__all__ = [
    # Core re-exports
    "check_displacement_node",
    # Subdivision
    "check_subdiv_setup",
    "get_objs_size_proportions",
    "recover_subsurf_levels",
    "remember_subsurf_levels",
    "setup_subdiv_to_max_polys",
    "update_enable_subdiv_setup",
    "update_subdiv_setup",
    # Layer modifiers
    "recover_layer_modifiers_and_transforms",
    "remember_and_disable_layer_modifiers_and_transforms",
    "remove_layer_modifiers_and_transforms",
    # Node utils
    "connect_to_original_node",
    "copy_default_value",
    # Property callbacks
    "bake_vcol_channel_items",
    "get_resize_image_entity_and_image",
    "merge_channel_items",
    "udim_tilenum_items",
    "update_bake_channel_uv_map",
    "update_resize_image_tile_number",
    # UV transfer
    "get_entities_to_transfer",
    "set_entities_which_using_the_same_image_or_segment",
    "transfer_uv",
    # Channel baking
    "bake_channel",
    "disable_temp_bake",
    "rebake_baked_images",
    "temp_bake",
    # Entity baking
    "bake_to_entity",
]
