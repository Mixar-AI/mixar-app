# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer cache node arrangement functions.

This module handles the arrangement of cache nodes for layers, channels,
and masks including procedural texture caches, image caches, and ramps.
"""

from ...node.loc import check_set_node_loc


def arrange_layer_cache_nodes(layer, tree, loc):
    """Arrange layer-level cache nodes.

    Positions cache nodes for layer-level procedural textures and images
    vertically from the given location.

    Args:
        layer: The layer object containing cache node references.
        tree: The node tree containing the cache nodes.
        loc (Vector): The starting location for arranging nodes (modified in place).

    Returns:
        Vector: The updated location after arranging all cache nodes.
    """
    cache_types = [
        ('cache_image', 270), ('cache_vcol', 200), ('cache_color', 200),
        ('cache_brick', 400), ('cache_checker', 170), ('cache_gradient', 140),
        ('cache_magic', 180), ('cache_musgrave', 270), ('cache_noise', 170),
        ('cache_voronoi', 170), ('cache_gabor', 170), ('cache_wave', 260),
    ]

    for cache_attr, y_offset in cache_types:
        if check_set_node_loc(tree, getattr(layer, cache_attr), loc, hide=False):
            loc.y -= y_offset

    return loc


def arrange_channel_cache_nodes(layer, tree, loc):
    """Arrange channel-level cache nodes.

    Positions cache nodes for channel-level procedural textures, images,
    ramps, and falloff curves vertically from the given location.

    Args:
        layer: The layer object containing channels with cache node references.
        tree: The node tree containing the cache nodes.
        loc (Vector): The starting location for arranging nodes (modified in place).

    Returns:
        Vector: The updated location after arranging all cache nodes.
    """
    cache_types = [
        ('cache_ramp', 250), ('cache_falloff_curve', 270), ('cache_image', 270),
        ('cache_vcol', 200), ('cache_brick', 400), ('cache_checker', 170),
        ('cache_gradient', 140), ('cache_magic', 180), ('cache_musgrave', 270),
        ('cache_noise', 170), ('cache_voronoi', 170), ('cache_gabor', 170),
        ('cache_wave', 260), ('cache_1_image', 270),
    ]

    for ch in layer.channels:
        for cache_attr, y_offset in cache_types:
            if hasattr(ch, cache_attr):
                if check_set_node_loc(tree, getattr(ch, cache_attr), loc, hide=False):
                    loc.y -= y_offset

    return loc


def arrange_mask_cache_nodes(layer, tree, loc):
    """Arrange mask-level cache nodes.

    Positions cache nodes for mask-level procedural textures, images,
    modifier ramps and curves vertically from the given location.

    Args:
        layer: The layer object containing masks with cache node references.
        tree: The node tree containing the cache nodes.
        loc (Vector): The starting location for arranging nodes (modified in place).

    Returns:
        Vector: The updated location after arranging all cache nodes.
    """
    cache_types = [
        ('cache_modifier_ramp', 250), ('cache_modifier_curve', 270),
        ('cache_image', 270), ('cache_vcol', 200), ('cache_brick', 400),
        ('cache_checker', 170), ('cache_gradient', 140), ('cache_magic', 180),
        ('cache_musgrave', 270), ('cache_noise', 170), ('cache_voronoi', 170),
        ('cache_gabor', 170), ('cache_wave', 260),
    ]

    for mask in layer.masks:
        for cache_attr, y_offset in cache_types:
            if hasattr(mask, cache_attr):
                if check_set_node_loc(tree, getattr(mask, cache_attr), loc, hide=False, parent_unset=True):
                    loc.y -= y_offset

    return loc
