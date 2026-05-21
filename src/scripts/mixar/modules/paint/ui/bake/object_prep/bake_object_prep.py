# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Object preparation utilities for baking.

This module re-exports all functions from the submodules for backward compatibility.
The implementation has been split into:
- bake_object_prep_colors.py: Color preparation utilities
- bake_object_prep_channels.py: Channel preparation utilities
- bake_object_prep_mesh.py: Mesh and object utilities
"""

# Re-export color preparation functions
from .bake_object_prep_colors import prepare_other_objs_colors

# Re-export channel preparation functions
from .bake_object_prep_channels import (
    prepare_other_objs_channels,
    recover_other_objs_channels,
)

# Re-export mesh/object utility functions
from .bake_object_prep_mesh import (
    get_bakeable_objects_and_meshes,
    get_duplicated_mesh_objects,
    get_merged_mesh_objects,
)

# Define __all__ for explicit public API
__all__ = [
    "prepare_other_objs_colors",
    "prepare_other_objs_channels",
    "recover_other_objs_channels",
    "get_bakeable_objects_and_meshes",
    "get_duplicated_mesh_objects",
    "get_merged_mesh_objects",
]
