# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Thumbnail generation system for Substance 3D Painter-style layer previews.

Uses Blender's bpy.utils.previews to generate and cache layer thumbnails.
Thumbnails are generated based on layer type and active channel context.
"""

import bpy
import bpy.utils.previews

from ...core.node.get_nodes import get_layer_source

# Global preview collection
_preview_collection = None

# Cache keys format: "material_name:layer_name:channel_idx"
_thumbnail_cache = {}

# Maximum cache size to prevent unbounded memory growth
MAX_THUMBNAIL_CACHE_SIZE = 200


def init_preview_collection():
    """Initialize the preview collection for layer thumbnails.

    Should be called during addon registration.
    """
    global _preview_collection
    if _preview_collection is None:
        _preview_collection = bpy.utils.previews.new()


def cleanup_preview_collection():
    """Cleanup the preview collection.

    Should be called during addon unregistration.
    """
    global _preview_collection, _thumbnail_cache
    if _preview_collection is not None:
        bpy.utils.previews.remove(_preview_collection)
        _preview_collection = None
    _thumbnail_cache.clear()


def get_cache_key(layer, channel_idx, material_name):
    """Generate a cache key for a layer thumbnail.

    Args:
        layer: MLayer instance.
        channel_idx: Index of the active channel.
        material_name: Name of the material containing the layer.

    Returns:
        str: Cache key string.
    """
    return f"{material_name}:{layer.name}:{channel_idx}"


def _prune_cache_if_needed():
    """Prune the thumbnail cache if it exceeds the maximum size.

    Removes the oldest half of entries when the cache is full.
    """
    global _thumbnail_cache, _preview_collection

    if len(_thumbnail_cache) <= MAX_THUMBNAIL_CACHE_SIZE:
        return

    # Remove oldest entries (first half of the dict)
    keys_to_remove = list(_thumbnail_cache.keys())[: MAX_THUMBNAIL_CACHE_SIZE // 2]
    for key in keys_to_remove:
        _thumbnail_cache.pop(key, None)
        if _preview_collection and key in _preview_collection:
            try:
                del _preview_collection[key]
            except KeyError:
                pass


def invalidate_layer_thumbnail(layer_name, material_name=None):
    """Invalidate cached thumbnails for a layer.

    Call this when layer content changes (paint operations, source image changes).

    Args:
        layer_name: Name of the layer to invalidate.
        material_name: Optional material name to limit invalidation scope.
    """
    global _thumbnail_cache, _preview_collection

    keys_to_remove = []
    for key in _thumbnail_cache:
        if layer_name in key:
            if material_name is None or material_name in key:
                keys_to_remove.append(key)

    for key in keys_to_remove:
        _thumbnail_cache.pop(key, None)
        if _preview_collection and key in _preview_collection:
            del _preview_collection[key]


def get_layer_thumbnail(layer, channel_idx=0, material_name=""):
    """Get or generate a thumbnail icon for a layer.

    Args:
        layer: MLayer instance.
        channel_idx: Index of the active channel (affects display for multi-channel layers).
        material_name: Name of the material containing the layer.

    Returns:
        int: Icon ID for use with layout.icon() or layout.template_icon().
             Returns 0 if thumbnail generation fails.
    """
    global _preview_collection, _thumbnail_cache

    if _preview_collection is None:
        init_preview_collection()

    cache_key = get_cache_key(layer, channel_idx, material_name)

    # Check cache
    if cache_key in _thumbnail_cache:
        preview = _preview_collection.get(cache_key)
        if preview:
            return preview.icon_id
        # IMAGE layers use Blender's built-in image preview instead of a
        # collection entry; the generated icon id is stored in the cache
        # below so the per-row get_layer_source lookup only runs once.
        cached_icon = _thumbnail_cache[cache_key]
        if cached_icon:
            return cached_icon

    # Prune cache if it's getting too large
    _prune_cache_if_needed()

    # Generate new thumbnail based on layer type
    icon_id = _generate_thumbnail(layer, channel_idx, cache_key)
    _thumbnail_cache[cache_key] = icon_id

    return icon_id


def _generate_thumbnail(layer, channel_idx, cache_key):
    """Generate a thumbnail for a layer.

    Args:
        layer: MLayer instance.
        channel_idx: Index of the active channel.
        cache_key: Cache key for storing the thumbnail.

    Returns:
        int: Generated icon ID, or 0 if generation fails.
    """
    global _preview_collection

    if layer.type == 'COLOR':
        # Generate solid color swatch
        return _generate_color_swatch(layer, channel_idx, cache_key)
    elif layer.type == 'IMAGE':
        # Generate thumbnail from source image
        return _generate_image_thumbnail(layer, channel_idx, cache_key)
    elif layer.type == 'GROUP':
        # Folders don't need thumbnails (use icon instead)
        return 0
    else:
        # Procedural layers - generate from preview if available
        return _generate_procedural_thumbnail(layer, cache_key)


def _generate_color_swatch(layer, channel_idx, cache_key):
    """Generate a solid color swatch thumbnail.

    Args:
        layer: MLayer instance (COLOR type).
        channel_idx: Index of the active channel.
        cache_key: Cache key for storing the thumbnail.

    Returns:
        int: Generated icon ID.
    """
    global _preview_collection

    # Get color from the layer's channel override
    color = (0.5, 0.5, 0.5, 1.0)  # Default gray
    if channel_idx < len(layer.channels):
        channel = layer.channels[channel_idx]
        if hasattr(channel, 'override_color'):
            color = tuple(channel.override_color)
            if len(color) == 3:
                color = (*color, 1.0)

    # Create preview with solid color
    size = 32
    preview = _preview_collection.new(cache_key)
    preview.image_size = (size, size)

    # Fill pixels with the color
    # Blender expects pixels as flat RGBA list
    pixels = []
    for _ in range(size * size):
        pixels.extend([color[0], color[1], color[2], color[3]])

    preview.image_pixels_float = pixels

    return preview.icon_id


def _generate_image_thumbnail(layer, channel_idx, cache_key):
    """Generate a thumbnail from a layer's source image.

    Args:
        layer: MLayer instance (IMAGE type).
        channel_idx: Index of the active channel.
        cache_key: Cache key for storing the thumbnail.

    Returns:
        int: Generated icon ID, or 0 if no image found.
    """
    global _preview_collection

    # Get the source image
    source = get_layer_source(layer)
    if not source or not hasattr(source, 'image') or not source.image:
        return 0

    image = source.image

    # Use Blender's built-in image preview
    if image.preview:
        return image.preview.icon_id

    # Generate preview if not available
    image.preview_ensure()
    if image.preview:
        return image.preview.icon_id

    return 0


def _generate_procedural_thumbnail(layer, cache_key):
    """Generate a thumbnail for procedural layers.

    For procedural layers (noise, brick, etc.), we use a placeholder icon
    since real-time preview would be expensive.

    Args:
        layer: MLayer instance (procedural type).
        cache_key: Cache key for storing the thumbnail.

    Returns:
        int: Icon ID (0 for now - using type icon instead).
    """
    # For procedural layers, we rely on the type icon in the UIList
    # Real procedural preview would require GPU rendering
    return 0


# Registration hooks
def register():
    """Register thumbnail generator system."""
    init_preview_collection()


def unregister():
    """Unregister thumbnail generator system."""
    cleanup_preview_collection()
