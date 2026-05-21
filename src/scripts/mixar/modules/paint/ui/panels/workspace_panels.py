# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Workspace Space Panels

Panel definitions for the Mixar workspace spaces (Layers, Properties, Assets, Export).
Integrated with the paint module backend for functional texture painting.

This module re-exports all panel classes from their individual modules for backward
compatibility. New code should import from the specific modules directly.
"""

# Re-export from layers_panel
from .layers_panel import MIXAR_LAYERS_PT_main

# Re-export from properties_panel
from .properties_panel import MIXAR_PROPERTIES_PT_main

# Re-export from assets_panel
from .assets_panel import MIXAR_ASSETS_PT_main

# Re-export from baking_panel
from .baking_panel import (
    BAKING_PT_main,
    is_baked_to_layer_type,
)


# Combined classes tuple for registration
classes = (
    MIXAR_LAYERS_PT_main,
    MIXAR_PROPERTIES_PT_main,
    MIXAR_ASSETS_PT_main,
    BAKING_PT_main,
)


# Re-export all public names for backward compatibility
__all__ = [
    'MIXAR_LAYERS_PT_main',
    'MIXAR_PROPERTIES_PT_main',
    'MIXAR_ASSETS_PT_main',
    'BAKING_PT_main',
    'is_baked_to_layer_type',
    'classes',
]
