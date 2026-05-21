# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vertex color editor module.

This module provides vertex color editing functionality including brush
activation, fill operations, face selection by color, and UI panels.

All components are re-exported from submodules for backward compatibility.
"""

import bpy
from bpy.props import PointerProperty

# Re-export brush utilities
from .brush_utils import (
    tex_default_brush_eraser_pairs,
    activate_essential_brush,
    activate_local_brush,
    activate_custom_brush,
    activate_unknown_custom_brush,
    set_brush_asset,
)

# Re-export operators
from .operators import (
    MSetActiveVcol,
    MSelectFacesByVcol,
    MVcolFillFaceCustom,
    MVcolFill,
)

# Re-export panels and draw functions
from .panels import (
    vcol_editor_draw,
    VIEW3D_PT_y_vcol_editor_ui,
    VIEW3D_PT_y_vcol_editor_tools,
)

# Re-export properties
from .properties import (
    MVcolEditorProps,
)

# Expose all public symbols for backward compatibility
__all__ = [
    # Brush utilities
    'tex_default_brush_eraser_pairs',
    'activate_essential_brush',
    'activate_local_brush',
    'activate_custom_brush',
    'activate_unknown_custom_brush',
    'set_brush_asset',
    # Operators
    'MSetActiveVcol',
    'MSelectFacesByVcol',
    'MVcolFillFaceCustom',
    'MVcolFill',
    # Panels
    'vcol_editor_draw',
    'VIEW3D_PT_y_vcol_editor_ui',
    'VIEW3D_PT_y_vcol_editor_tools',
    # Properties
    'MVcolEditorProps',
    # Registration
    'register',
    'unregister',
]


def register():
    """Registers all vertex color editor classes and properties with Blender.

    Registers panel classes, property groups, and operator classes. Also adds
    the ve_edit property group to Scene for storing editor state.

    This function is idempotent - safe to call multiple times.

    Args:
        None

    Returns:
        None
    """
    classes = [
        VIEW3D_PT_y_vcol_editor_ui,
        MVcolEditorProps,
        MVcolFill,
        MSelectFacesByVcol,
        MVcolFillFaceCustom,
        MSetActiveVcol,
    ]
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise

    if not hasattr(bpy.types.Scene, 've_edit'):
        bpy.types.Scene.ve_edit = PointerProperty(type=MVcolEditorProps)


def unregister():
    """Unregisters all vertex color editor classes from Blender.

    Unregisters panel classes, property groups, and operator classes that were
    registered by the register() function.

    Args:
        None

    Returns:
        None
    """
    bpy.utils.unregister_class(VIEW3D_PT_y_vcol_editor_ui)
    bpy.utils.unregister_class(MVcolEditorProps)

    bpy.utils.unregister_class(MVcolFill)
    bpy.utils.unregister_class(MSelectFacesByVcol)
    bpy.utils.unregister_class(MVcolFillFaceCustom)
    bpy.utils.unregister_class(MSetActiveVcol)
