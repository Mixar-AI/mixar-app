# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Procedural layer operators for Mixar layers system.

This module serves as a coordinator that re-exports all procedural layer
operators from their respective submodules.

Submodules:
- procedural_pattern_ops: Built-in procedural patterns (Brick, Noise, etc.)
- procedural_library_ops: Material library browsing popup
- procedural_material_ops: Custom material application operators
"""

# Re-export pattern operators
from .procedural_pattern_ops import (
    LAYERS_OT_AddProceduralLayer,
    LAYERS_MT_ProceduralLayerMenu,
)

# Re-export library operators
from .procedural_library_ops import (
    LAYERS_OT_ProceduralMaterialLibraryPopup,
    LAYERS_MT_CustomProceduralMenu,
)

# Re-export material operators
from .procedural_material_ops import (
    LAYERS_OT_AddCustomProceduralLayer,
    LAYERS_OT_ApplyMaterialToLayer,
    LAYERS_OT_ClearLayerMaterial,
)


# Classes are registered by their respective source modules
# (procedural_pattern_ops.py, procedural_library_ops.py, procedural_material_ops.py)
# No classes tuple here to avoid double registration by bootstrap


# Define __all__ for explicit exports
__all__ = [
    # Pattern operators
    'LAYERS_OT_AddProceduralLayer',
    'LAYERS_MT_ProceduralLayerMenu',
    # Library operators
    'LAYERS_OT_ProceduralMaterialLibraryPopup',
    'LAYERS_MT_CustomProceduralMenu',
    # Material operators
    'LAYERS_OT_AddCustomProceduralLayer',
    'LAYERS_OT_ApplyMaterialToLayer',
    'LAYERS_OT_ClearLayerMaterial',
]
