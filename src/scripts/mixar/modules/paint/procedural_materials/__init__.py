# SPDX-FileCopyrightText: 2026 Mixar AI
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Procedural Materials Module for Ucupaint

This module provides functionality for loading and managing custom procedural materials
that can be used as layer types in Ucupaint. The material library is served by the
backend catalog; only the user's own AI-generated materials live on disk (in the
user data directory). No material scripts or thumbnails ship with the app.
"""

from . import material_registry

# Export main functions
from .material_registry import (
    get_registry,
    register_material,
    get_material,
    get_all_materials,
    is_custom_material,
    get_node_group,
    load_matgen_materials,
    unload_all_materials,
    ProceduralMaterial
)

__all__ = [
    'get_registry',
    'register_material',
    'get_material',
    'get_all_materials',
    'is_custom_material',
    'get_node_group',
    'load_matgen_materials',
    'unload_all_materials',
    'ProceduralMaterial',
    'material_registry'
]
