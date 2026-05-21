# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Common utility functions for the paint module.

This module re-exports functions from sub-modules for backward compatibility.
The actual implementations are in:
- common_layer_types.py: Layer type definitions and callbacks
- common_addon.py: Addon and version utilities
- common_properties.py: Property and layer/mask utilities
- common_nodes.py: Node utility functions
- common_animation.py: Animation, FCurve, and driver utilities
- common_entity.py: Entity property and input utilities
- common_ui.py: UI utility functions
"""

# Layer type definitions and callbacks
from .common_layer_types import (
    _base_layer_type_items,
    _dynamic_layer_type_items,
    get_layer_type_items_callback,
)

# Addon and version utilities
from .common_addon import (
    version_tuple,
    get_addon_name,
    get_addon_title,
    id_generator,
)

# Property and layer/mask utilities
from .common_properties import (
    is_parallax_enabled,
    is_bump_distance_relevant,
    is_object_work_with_uv,
    load_hemi_props,
    save_hemi_props,
    is_mesh_flat_shaded,
    is_mask_using_vector,
    get_channel_index,
    get_active_layer_safe,
    get_active_mask_safe,
    get_write_height,
    get_first_mirror_modifier,
)

# Node utility functions
from .common_nodes import (
    get_node,
    get_vcol_bl_idname,
    set_source_vcol_name,
    set_mix_clamp,
    get_mix_color_indices,
    is_first_socket_bsdf,
    is_valid_bsdf_node,
)

# Animation, FCurve, and driver utilities
from .common_animation import (
    get_action_and_driver_fcurves,
    get_material_fcurves,
    get_material_drivers,
    get_material_fcurves_and_drivers,
    get_mp_fcurves,
    get_mp_drivers,
    get_mp_fcurves_and_drivers,
)

# Entity property and input utilities
from .common_entity import (
    get_entity_input_name,
    get_entity_prop_input,
    set_entity_prop_value,
    get_entity_prop_value,
)

# UI utility functions
from .common_ui import (
    split_layout,
)

# Define __all__ for explicit exports
__all__ = [
    # Layer types
    "_base_layer_type_items",
    "_dynamic_layer_type_items",
    "get_layer_type_items_callback",
    # Addon utilities
    "version_tuple",
    "get_addon_name",
    "get_addon_title",
    "id_generator",
    # Property utilities
    "is_parallax_enabled",
    "is_bump_distance_relevant",
    "is_object_work_with_uv",
    "load_hemi_props",
    "save_hemi_props",
    "is_mesh_flat_shaded",
    "is_mask_using_vector",
    "get_channel_index",
    "get_active_layer_safe",
    "get_active_mask_safe",
    "get_write_height",
    "get_first_mirror_modifier",
    # Node utilities
    "get_node",
    "get_vcol_bl_idname",
    "set_source_vcol_name",
    "set_mix_clamp",
    "get_mix_color_indices",
    "is_first_socket_bsdf",
    "is_valid_bsdf_node",
    # Animation utilities
    "get_action_and_driver_fcurves",
    "get_material_fcurves",
    "get_material_drivers",
    "get_material_fcurves_and_drivers",
    "get_mp_fcurves",
    "get_mp_drivers",
    "get_mp_fcurves_and_drivers",
    # Entity utilities
    "get_entity_input_name",
    "get_entity_prop_input",
    "set_entity_prop_value",
    "get_entity_prop_value",
    # UI utilities
    "split_layout",
]
