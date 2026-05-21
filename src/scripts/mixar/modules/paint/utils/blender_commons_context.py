# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Context and version utilities for Blender operations."""

import os

import bpy


def get_window_context():
    """Get a valid window context for operations that need a window.

    This is useful when running from panels that don't have a window context
    (like Properties panels). It finds any available window and returns a
    context override dict.

    Returns:
        dict: Context override dictionary with window and scene, or None if no window found.

    Example:
        ctx = get_window_context()
        if ctx:
            with bpy.context.temp_override(**ctx):
                # Your operation that needs window context
                bpy.ops.render.render()
    """
    # Try to find any window
    for window in bpy.context.window_manager.windows:
        return {
            'window': window,
            'screen': window.screen,
            'scene': bpy.context.scene,
        }
    return None


def get_viewport_context():
    """Get a context override dict for 3D viewport operations.

    Returns a context override dict that can be used with bpy.context.temp_override()
    to execute operators that require VIEW_3D area context.

    Returns:
        dict: Context override dictionary with window, screen, area, and region,
              or None if no 3D viewport is found.

    Example:
        override = get_viewport_context()
        if override:
            with bpy.context.temp_override(**override):
                bpy.ops.view3d.some_operator()
    """
    context = bpy.context

    # Find the 3D Viewport area
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                # Get the main window region
                for region in area.regions:
                    if region.type == 'WINDOW':
                        return {
                            'window': window,
                            'screen': window.screen,
                            'area': area,
                            'region': region,
                            'scene': context.scene,
                        }

    # No 3D viewport found
    return None


def get_bpy_data():
    """Get the Blender data structure containing all loaded data.

    Returns:
        bpy.types.BlendData: The main Blender data structure with access to scenes, objects, materials, etc.
    """
    return bpy.data


def get_bpy_utils():
    """Get the Blender utilities module.

    Returns:
        module: The bpy.utils module.
    """
    return bpy.utils


def get_current_filepath():
    """Get the absolute directory path of the current file.

    Returns:
        str: Absolute path to the directory containing this file, with trailing separator.
    """
    return os.path.dirname(bpy.path.abspath(__file__)) + os.sep


def get_current_blender_version_str():
    """Get the current Blender version as a formatted string.

    Returns:
        str: Blender version in format "major.minor.patch" (e.g., "3.6.0").
    """
    return str(bpy.app.version).replace(", ", ".").replace("(", "").replace(")", "")


def is_online():
    """Check if Blender has online access enabled.

    Returns:
        bool: True if online access is available, False otherwise. For Blender < 4.2, always returns True.
    """
    return not is_bl_newer_than(4, 2) or bpy.app.online_access


def is_bl_newer_than(major, minor=0, patch=0):
    """Check if the current Blender version is newer than or equal to the specified version.

    Args:
        major (int): Major version number.
        minor (int, optional): Minor version number. Defaults to 0.
        patch (int, optional): Patch version number. Defaults to 0.

    Returns:
        bool: True if current version >= specified version, False otherwise.
    """
    return bpy.app.version >= (major, minor, patch)


def is_bl_equal(major, minor=None, patch=None):
    """Check if the current Blender version equals the specified version.

    Args:
        major (int): Major version number.
        minor (int, optional): Minor version number. Defaults to None.
        patch (int, optional): Patch version number. Defaults to None.

    Returns:
        bool: True if versions match, False otherwise. If minor/patch are None, only checks up to the specified level.
    """
    if minor is None and patch is None:
        return bpy.app.version[0] == major
    elif patch is None:
        return bpy.app.version[:2] == (major, minor)
    else:
        return bpy.app.version == (major, minor, patch)


def is_created_before(major, minor=0, patch=0):
    """Check if the current blend file was created with a version before the specified version.

    Args:
        major (int): Major version number.
        minor (int, optional): Minor version number. Defaults to 0.
        patch (int, optional): Patch version number. Defaults to 0.

    Returns:
        bool: True if file version < specified version, False otherwise.
    """
    return bpy.data.version < (major, minor, patch)


def get_bpytypes():
    """Get the Blender types module.

    Returns:
        module: The bpy.types module containing all Blender RNA type definitions.
    """
    return bpy.types
