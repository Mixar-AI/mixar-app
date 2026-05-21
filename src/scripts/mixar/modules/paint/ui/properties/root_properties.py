# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Root paint properties module.

This module re-exports all property classes from split modules for
backward compatibility. All classes are imported and exposed from
their respective modules.
"""

import bpy
from bpy.props import PointerProperty

# Import all classes from split modules for backward compatibility
from .channel_properties import (
    MNodeConnections,
    MPaintChannel,
)
from .channel_properties import classes as channel_classes

from .material_properties import MPaintMaterialProps
from .material_properties import classes as material_classes

from .uv_properties import MPaintUV
from .uv_properties import classes as uv_classes

from .main_paint_properties import MPaint
from .main_paint_properties import classes as main_paint_classes

from .wm_properties import MPaintTimer, MPaintWMProps
from .wm_properties import classes as wm_classes

from .scene_object_properties import (
    MPaintObjectProps,
    MPaintObjectUVHash,
    MPaintSceneProps,
)
from .scene_object_properties import classes as scene_object_classes


# Re-export all classes for backward compatibility
__all__ = [
    "MNodeConnections",
    "MPaintChannel",
    "MPaintMaterialProps",
    "MPaintUV",
    "MPaint",
    "MPaintWMProps",
    "MPaintTimer",
    "MPaintSceneProps",
    "MPaintObjectUVHash",
    "MPaintObjectProps",
    "classes",
    "register",
    "unregister",
]


# Combined classes list in registration order
# Order matters: dependencies must be registered before dependents
classes = [
    MNodeConnections,
    MPaintChannel,
    MPaintMaterialProps,
    MPaintUV,
    MPaint,
    MPaintWMProps,
    MPaintTimer,
    MPaintSceneProps,
    MPaintObjectUVHash,
    MPaintObjectProps,
]


def register():
    """Register all property classes and attach to Blender types.

    Registers all MPaint property group classes and attaches them to appropriate
    Blender types (ShaderNodeTree, Material, WindowManager, Scene, Object).

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

    if not hasattr(bpy.types.ShaderNodeTree, "mp"):
        bpy.types.ShaderNodeTree.mp = PointerProperty(type=MPaint)
    if not hasattr(bpy.types.Material, "mp"):
        bpy.types.Material.mp = PointerProperty(type=MPaintMaterialProps)
    if not hasattr(bpy.types.WindowManager, "mptimer"):
        bpy.types.WindowManager.mptimer = PointerProperty(type=MPaintTimer)
    if not hasattr(bpy.types.WindowManager, "mpprops"):
        bpy.types.WindowManager.mpprops = PointerProperty(type=MPaintWMProps)
    if not hasattr(bpy.types.Scene, "mp"):
        bpy.types.Scene.mp = PointerProperty(type=MPaintSceneProps)
    if not hasattr(bpy.types.Object, "mp"):
        bpy.types.Object.mp = PointerProperty(type=MPaintObjectProps)


def unregister():
    """Unregister all property classes.

    Unregisters all MPaint property group classes in reverse order.
    Also removes pointer properties from Blender types.

    Args:
        None

    Returns:
        None
    """
    # Remove pointer properties from Blender types first
    if hasattr(bpy.types.ShaderNodeTree, "mp"):
        del bpy.types.ShaderNodeTree.mp
    if hasattr(bpy.types.Material, "mp"):
        del bpy.types.Material.mp
    if hasattr(bpy.types.WindowManager, "mptimer"):
        del bpy.types.WindowManager.mptimer
    if hasattr(bpy.types.WindowManager, "mpprops"):
        del bpy.types.WindowManager.mpprops
    if hasattr(bpy.types.Scene, "mp"):
        del bpy.types.Scene.mp
    if hasattr(bpy.types.Object, "mp"):
        del bpy.types.Object.mp

    # Then unregister classes
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass  # Class may not be registered
