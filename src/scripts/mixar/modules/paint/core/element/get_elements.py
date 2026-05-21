# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Element retrieval functions module.

This module serves as the main entry point for element retrieval functions.
All functions are re-exported from their respective submodules for backward
compatibility.

Submodules:
- image_editor: Image editor space related functions
- image_utils: Image and mask color utility functions
- modifiers: Modifier retrieval functions
- vertex_colors: Vertex color attribute functions
- uv_utils: UV layer utility functions
- hash_utils: Mesh and UV hashing functions
"""

# Image editor functions
from .image_editor import (
    get_edit_image_editor_space,
    get_first_unpinned_image_editor_space,
    get_first_image_editor_image,
)

# Image and mask color utility functions
from .image_utils import (
    get_image_mask_base_color,
    get_mask_color_id_color,
)

# Modifier functions
from .modifiers import (
    get_subsurf_modifier,
    get_displace_modifier,
    get_multires_modifier,
    get_armature_modifier,
)

# Vertex color functions
from .vertex_colors import (
    get_vcol_index,
    get_vertex_color_names_from_geonodes,
    get_vertex_color_names,
    get_active_vertex_color,
    get_vcol_data_type_and_domain_by_name,
    get_vcol_from_source,
    get_layer_vcol,
)

# UV layer functions
from .uv_utils import (
    get_uv_layer_index,
    get_active_render_uv,
    get_default_uv_name,
    get_relevant_uv,
    get_correct_uv_neighbor_resolution,
    get_tilenums_height,
    get_udim_segment_tiles_height,
)

# Hash functions
from .hash_utils import (
    get_mesh_hash,
    get_uv_hash,
)

# Re-exports from other locations for backward compatibility
from ..layer.layer_utils import get_uv_layers
from ..node.node_tree_utils import get_source_vcol_name, get_vertex_colors

# Define __all__ for explicit exports
__all__ = [
    # Image editor functions
    'get_edit_image_editor_space',
    'get_first_unpinned_image_editor_space',
    'get_first_image_editor_image',
    # Image and mask color functions
    'get_image_mask_base_color',
    'get_mask_color_id_color',
    # Modifier functions
    'get_subsurf_modifier',
    'get_displace_modifier',
    'get_multires_modifier',
    'get_armature_modifier',
    # Vertex color functions
    'get_vcol_index',
    'get_vertex_color_names_from_geonodes',
    'get_vertex_color_names',
    'get_active_vertex_color',
    'get_vcol_data_type_and_domain_by_name',
    'get_vcol_from_source',
    'get_layer_vcol',
    # UV layer functions
    'get_uv_layer_index',
    'get_active_render_uv',
    'get_default_uv_name',
    'get_relevant_uv',
    'get_correct_uv_neighbor_resolution',
    'get_tilenums_height',
    'get_udim_segment_tiles_height',
    # Hash functions
    'get_mesh_hash',
    'get_uv_hash',
    # Re-exported for backward compatibility
    'get_uv_layers',
    'get_source_vcol_name',
    'get_vertex_colors',
]
