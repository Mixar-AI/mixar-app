# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vector displacement map library.

This module provides functions for creating and managing vector displacement maps,
including materials for baking tangent/bitangent vectors and shader/geometry node trees.

All functions are re-exported from submodules for backward compatibility.
"""

# Re-export constants
from .vdm_constants import (
    BSIGN_ATTR,
    GEO_TANGENT2OBJECT,
    GEO_VDM_LOADER,
    MAT_BITANGENT_BAKE,
    MAT_OFFSET_TANGENT_SPACE,
    MAT_TANGENT_BAKE,
    OFFSET_ATTR,
    SHA_BITANGENT_CALC,
    SHA_OBJECT2TANGENT,
    SHA_PACK_VECTOR,
)

# Re-export utility functions
from .vdm_utils import create_link

# Re-export bake material functions
from .vdm_bake_materials import (
    get_bitangent_bake_mat,
    get_offset_bake_mat,
    get_tangent_bake_mat,
)

# Re-export shader tree functions
from .vdm_shader_trees import (
    get_bitangent_calc_shader_tree,
    get_object2tangent_shader_tree,
    get_pack_vector_shader_tree,
)

# Re-export geometry tree functions
from .vdm_geometry_trees import (
    get_tangent2object_geo_tree,
    get_vdm_loader_geotree,
)

# Define __all__ for explicit exports
__all__ = [
    # Constants
    "GEO_TANGENT2OBJECT",
    "GEO_VDM_LOADER",
    "MAT_OFFSET_TANGENT_SPACE",
    "MAT_TANGENT_BAKE",
    "MAT_BITANGENT_BAKE",
    "SHA_PACK_VECTOR",
    "SHA_OBJECT2TANGENT",
    "SHA_BITANGENT_CALC",
    "OFFSET_ATTR",
    "BSIGN_ATTR",
    # Utility functions
    "create_link",
    # Bake material functions
    "get_tangent_bake_mat",
    "get_bitangent_bake_mat",
    "get_offset_bake_mat",
    # Shader tree functions
    "get_bitangent_calc_shader_tree",
    "get_pack_vector_shader_tree",
    "get_object2tangent_shader_tree",
    # Geometry tree functions
    "get_tangent2object_geo_tree",
    "get_vdm_loader_geotree",
]
