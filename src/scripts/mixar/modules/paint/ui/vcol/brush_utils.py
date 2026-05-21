# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Brush activation utilities for vertex color editing.

This module provides functions to activate brushes from various asset libraries
including essential, local, and custom libraries.
"""

import bpy
import os
from pathlib import Path

from .....config.logging_config import get_logger

logger = get_logger(__name__)


def _get_view3d_context():
    """Find a VIEW_3D window/area/region for context override.

    brush.asset_activate requires a paint-capable area. Calling it from
    a Properties panel context crashes Blender. This finds the first
    VIEW_3D area to use with bpy.context.temp_override().

    Returns:
        Tuple of (window, area, region) or None if no VIEW_3D found.
    """
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        return window, area, region
    return None


def _brush_asset_activate(**kwargs):
    """Call bpy.ops.brush.asset_activate with a safe VIEW_3D context.

    Wraps the operator call with a temp_override when a VIEW_3D area
    is available, falling back to a direct call otherwise.

    Args:
        **kwargs: Arguments passed to bpy.ops.brush.asset_activate.

    Returns:
        True if successful, False otherwise.
    """
    ctx = _get_view3d_context()
    if ctx:
        window, area, region = ctx
        with bpy.context.temp_override(
            window=window, area=area, region=region
        ):
            bpy.ops.brush.asset_activate(**kwargs)
    else:
        bpy.ops.brush.asset_activate(**kwargs)
    return True


# Default brush to eraser mappings for texture painting
tex_default_brush_eraser_pairs = {
    'Paint Hard': 'Erase Hard',
    'Paint Soft': 'Erase Soft',
    'Paint Hard Pressure': 'Erase Hard Pressure',
    'Smear': 'Erase Soft',
    'Airbrush': 'Erase Soft',
    'Paint Soft Pressure': 'Erase Soft',
    'Clone': 'Erase Hard',
    'Blur': 'Erase Soft',
    'Fill': 'Erase Hard',
    'Mask': 'Erase Soft',
}


def activate_essential_brush(brush_name, essential_asset_identifier):
    """Activates an essential Blender brush asset from the essentials library.

    Args:
        brush_name (str): Name of the brush to activate.
        essential_asset_identifier (str): Path identifier for the essential asset blend file.

    Returns:
        bool: True if the brush was successfully activated, False otherwise.
    """
    try:
        return _brush_asset_activate(
            asset_library_type='ESSENTIALS',
            asset_library_identifier='',
            relative_asset_identifier=essential_asset_identifier + os.sep + "Brush" + os.sep + brush_name
        )
    except Exception as e:
        logger.error("Exception: %s", e)

    return False


def activate_local_brush(brush_name):
    """Activates a brush asset from the local asset library.

    Args:
        brush_name (str): Name of the brush to activate.

    Returns:
        bool: True if the brush was successfully activated, False otherwise.
    """
    try:
        return _brush_asset_activate(
            asset_library_type='LOCAL',
            asset_library_identifier='',
            relative_asset_identifier='Brush' + os.sep + brush_name
        )
    except Exception as e:
        logger.error("Exception: %s", e)

    return False


def activate_custom_brush(brush_name, filepath):
    """Activates a brush asset from a custom asset library at a known filepath.

    Args:
        brush_name (str): Name of the brush to activate.
        filepath (str): File path to the blend file containing the brush asset.

    Returns:
        bool: True if the brush was successfully activated, False otherwise.
    """
    # Get asset library name and blend path
    asset_libraries = bpy.context.preferences.filepaths.asset_libraries
    library_name = ''
    blend_path = ''
    for al in asset_libraries:
        if filepath.startswith(al.path):
            library_name = al.name
            blend_path = str(filepath).replace(str(al.path) + os.sep, '')
            break

    try:
        return _brush_asset_activate(
            asset_library_type='CUSTOM',
            asset_library_identifier=library_name,
            relative_asset_identifier=blend_path + os.sep + "Brush" + os.sep + brush_name
        )
    except Exception as e:
        logger.error("Exception: %s", e)

    return False


def activate_unknown_custom_brush(brush_name):
    """Searches all custom asset libraries for a brush and activates it when found.

    Iterates through all registered custom asset libraries, searching blend files
    for the specified brush asset.

    Args:
        brush_name (str): Name of the brush to search for and activate.

    Returns:
        bool: True if the brush was found and successfully activated, False otherwise.
    """
    asset_libraries = bpy.context.preferences.filepaths.asset_libraries

    # Look for brush in all asset libraries
    for asset_library in asset_libraries:
        library_name = asset_library.name
        library_path = Path(asset_library.path)
        blend_files = [fp for fp in library_path.glob("**/*.blend") if fp.is_file()]
        for blend_file in blend_files:
            with bpy.data.libraries.load(str(blend_file), assets_only=True) as (file_contents, _):
                if brush_name in file_contents.brushes:
                    blend_path = str(blend_file).replace(str(library_path) + os.sep, '')
                    try:
                        return _brush_asset_activate(
                            asset_library_type='CUSTOM',
                            asset_library_identifier=library_name,
                            relative_asset_identifier=blend_path + "\\Brush\\" + brush_name
                        )
                    except Exception as e:
                        logger.error("Exception: %s", e)

    return False


def set_brush_asset(brush_name, mode='TEXTURE_PAINT'):
    """Sets the active brush asset for the specified paint mode.

    Attempts to activate a brush by searching in order: essential library,
    local library, and custom libraries. Determines the appropriate library
    based on the brush's origin if it already exists.

    Args:
        brush_name (str): Name of the brush to set as active.
        mode (str, optional): Paint mode context. Options are 'TEXTURE_PAINT',
            'VERTEX_PAINT', or 'SCULPT'. Defaults to 'TEXTURE_PAINT'.

    Returns:
        None
    """
    # Get essential asset identifier path
    essential_asset_prefix = "brushes\\essentials_brushes-mesh_"
    mode_type = ''
    if mode == 'TEXTURE_PAINT':
        mode_type = 'texture'
    elif mode == 'VERTEX_PAINT':
        mode_type = 'vertex'
    elif mode == 'SCULPT':
        mode_type = 'sculpt'
    essential_asset_identifier = essential_asset_prefix + mode_type + ".blend"

    # Try to get brush from local data
    brush = bpy.data.brushes.get(brush_name)

    if not brush:
        # Look for essential brush
        activated = activate_essential_brush(brush_name, essential_asset_identifier)

        # Look for local brush
        if not activated:
            activated = activate_local_brush(brush_name)

        # Look for custom brush
        if not activated:
            activated = activate_unknown_custom_brush(brush_name)
    else:

        if brush.library and brush.library.name.startswith('essentials_'):
            # Essential brush
            activate_essential_brush(brush_name, essential_asset_identifier)
        elif not brush.library:
            # Local brush
            activate_local_brush(brush_name)
        else:
            # Custom brush
            activate_custom_brush(brush_name, brush.library.filepath)
