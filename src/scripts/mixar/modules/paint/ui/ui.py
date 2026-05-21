# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main UI module for Mixar paint system.

This module provides the registration and initialization of all UI-related
property groups for the Mixar paint system. It re-exports all public symbols
from sub-modules for backward compatibility.

The UI system is split into the following modules:
- channel_filter: Channel filter enum items callback
- ui_paint: MPaintUI and MMaterialUI property groups
- ui_state: MixarUIState and MixarUILayer property groups
- properties/ui_properties: Low-level UI property groups
"""

import bpy
from bpy.props import IntProperty, PointerProperty, StringProperty

from ....config.logging_config import get_logger

logger = get_logger(__name__)

# Import from sub-modules
from .properties.ui_properties import (
    MBakeTargetUI,
    MChannelUI,
    MLayerUI,
    MMaskChannelUI,
    MMaskUI,
    MModifierUI,
)

from ..procedural_materials import material_registry
from .operators.matgen_ops import register_wm_props, unregister_wm_props

# Import and re-export from refactored modules
from .channel_filter import get_channel_filter_items
from .ui_paint import MMaterialUI, MPaintUI
from .ui_state import (
    MixarUILayer,
    MixarUIState,
    update_active_channel_filter,
    update_brush_value,
)
from .utils import material_preview_manager

# Re-export all public symbols for backward compatibility
__all__ = [
    # From channel_filter
    'get_channel_filter_items',
    # From ui_paint
    'MMaterialUI',
    'MPaintUI',
    # From ui_state
    'MixarUILayer',
    'MixarUIState',
    'update_active_channel_filter',
    'update_brush_value',
    # From properties/ui_properties
    'MBakeTargetUI',
    'MChannelUI',
    'MLayerUI',
    'MMaskChannelUI',
    'MMaskUI',
    'MModifierUI',
]

classes = [
    MModifierUI,
    MMaskChannelUI,
    MMaskUI,
    MChannelUI,
    MLayerUI,
    MBakeTargetUI,
    MMaterialUI,
    MPaintUI,
    MixarUILayer,
    MixarUIState,
]


def register():
    """Register UI property groups and initialize Mixar paint UI system.

    Registers all UI-related property groups with Blender, sets up properties
    on Scene and WindowManager for UI state management, and loads procedural
    materials from the material registry.

    This function is idempotent - safe to call multiple times.

    Args:
        None

    Returns:
        None
    """
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise

    if not hasattr(bpy.types.Scene, 'mpui'):
        bpy.types.Scene.mpui = PointerProperty(type=MPaintUI)
    if not hasattr(bpy.types.WindowManager, 'mpui'):
        bpy.types.WindowManager.mpui = PointerProperty(type=MPaintUI)

    # Register modern Mixar UI state
    if not hasattr(bpy.types.WindowManager, 'mixar_ui'):
        bpy.types.WindowManager.mixar_ui = PointerProperty(type=MixarUIState)

    # Register layer move popup properties
    if not hasattr(bpy.types.WindowManager, 'mixar_move_layer_idx'):
        bpy.types.WindowManager.mixar_move_layer_idx = IntProperty(default=-1)
    if not hasattr(bpy.types.WindowManager, 'mixar_move_direction'):
        bpy.types.WindowManager.mixar_move_direction = StringProperty(default="UP")
    if not hasattr(bpy.types.WindowManager, 'mixar_move_group_name'):
        bpy.types.WindowManager.mixar_move_group_name = StringProperty(default="")

    # Register MatGen WindowManager properties (must come before load_server_catalog
    # so the timer safety check — hasattr(wm, 'mixar_matgen_status') — passes)
    register_wm_props()

    # Fetch catalog from server; falls back to local files if unavailable
    try:
        material_registry.load_server_catalog()
    except Exception as e:
        logger.warning("Failed to start server catalog fetch: %s", e)

    # Register material preview manager
    material_preview_manager.register()


def unregister():
    """Unregister UI property groups and cleanup Mixar paint UI system.

    Unloads all procedural materials, removes properties from Scene and
    WindowManager, and unregisters all UI-related property groups from Blender.
    This function is called during addon deactivation or uninstallation.

    Args:
        None

    Returns:
        None
    """
    # Unregister MatGen WindowManager properties
    unregister_wm_props()

    # Unregister material preview manager (must be before unloading materials)
    material_preview_manager.unregister()

    # Unload procedural materials
    try:
        material_registry.unload_all_materials()
    except Exception as e:
        logger.warning("Failed to unload procedural materials: %s", e)

    # Clean up layer move popup properties
    if hasattr(bpy.types.WindowManager, 'mixar_move_layer_idx'):
        del bpy.types.WindowManager.mixar_move_layer_idx
    if hasattr(bpy.types.WindowManager, 'mixar_move_direction'):
        del bpy.types.WindowManager.mixar_move_direction
    if hasattr(bpy.types.WindowManager, 'mixar_move_group_name'):
        del bpy.types.WindowManager.mixar_move_group_name

    if hasattr(bpy.types.WindowManager, 'mixar_ui'):
        del bpy.types.WindowManager.mixar_ui
    if hasattr(bpy.types.Scene, 'mpui'):
        del bpy.types.Scene.mpui
    if hasattr(bpy.types.WindowManager, 'mpui'):
        del bpy.types.WindowManager.mpui
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass  # Class was never registered
