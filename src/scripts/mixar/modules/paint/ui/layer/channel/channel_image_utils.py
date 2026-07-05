# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Utility functions for channel image operations.

This module provides helper functions for detecting normal maps from filenames
and getting lists of existing images for selection.
"""

import bpy


def is_normal_map_filename(filename):
    """Check if filename suggests this is a normal map.

    Args:
        filename: Image filename (without extension)

    Returns:
        bool: True if filename suggests normal map
    """
    name_lower = filename.lower()

    # Check for common normal map naming patterns
    normal_patterns = [
        'normal', 'norm', '_nor', '.nor', '_n.',
        '_normal', '_nrm', '_norm', 'normalmap'
    ]

    # Exclude displacement maps that might contain 'normal' word
    exclude_patterns = ['displacement', 'disp', 'height']

    for exclude in exclude_patterns:
        if exclude in name_lower:
            return False

    for pattern in normal_patterns:
        if pattern in name_lower:
            return True

    # Check for suffix patterns
    if name_lower.endswith(('_n', '_nor', '_nrm', '_normal')):
        return True

    return False


def get_existing_images(self, context):
    """Get list of existing images in blend file for enum property.

    Args:
        self: Operator instance
        context: Blender context

    Returns:
        list: List of (identifier, name, description) tuples for EnumProperty.
    """
    items = []
    for img in bpy.data.images:
        # Skip render results and viewer nodes
        if img.type in {'RENDER_RESULT', 'COMPOSITING'}:
            continue
        items.append((img.name, img.name, f"Use {img.name}"))
    if not items:
        items.append(('NONE', "No Images", "No images available"))
    return items
