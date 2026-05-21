# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy

from ...core.element.update_image import set_image_pixels
from ...core.layer.get_layers import (
    get_layer_ids_with_specific_segment,
    get_masks_with_specific_segment,
)


def is_tile_available(x, y, width, height, atlas):
    """Checks if a tile position in the atlas is available for a new segment.

    Tests whether a rectangular area at the specified tile coordinates overlaps
    with any existing segments in the atlas.

    Args:
        x (int): The x-coordinate of the tile position.
        y (int): The y-coordinate of the tile position.
        width (int): Width of the proposed segment in pixels.
        height (int): Height of the proposed segment in pixels.
        atlas: The YImageAtlas property group to check.

    Returns:
        bool: True if the tile position is available, False if it overlaps with existing segments.
    """

    start_x = width * x
    end_x = start_x + width - 1

    start_y = height * y
    end_y = start_y + height - 1

    for segment in atlas.segments:

        segment_start_x = segment.width * segment.tile_x
        segment_end_x = segment_start_x + segment.width - 1

        segment_start_y = segment.height * segment.tile_y
        segment_end_y = segment_start_y + segment.height - 1

        if (
            (start_x >= segment_start_x and start_x <= segment_end_x)
            or (end_x <= segment_end_x and end_x >= segment_start_x)
        ) and (
            (start_y >= segment_start_y and start_y <= segment_end_y)
            or (end_y <= segment_end_y and end_y >= segment_start_y)
        ):
            return False

    return True


def get_available_tile(width, height, atlas):
    """Finds the first available tile position for a segment of given dimensions.

    Iterates through all possible tile positions in the atlas from bottom-left
    to top-right to find an available space.

    Args:
        width (int): Width of the segment in pixels.
        height (int): Height of the segment in pixels.
        atlas: The YImageAtlas property group to search.

    Returns:
        list or empty list: [x, y] coordinates of the available tile, or [] if no space found.
    """
    atlas_img = atlas.id_data

    num_x = int(atlas_img.size[0] / width)
    num_y = int(atlas_img.size[1] / height)

    for y in range(num_y):
        for x in range(num_x):
            if is_tile_available(x, y, width, height, atlas):
                return [x, y]

    return []


def clear_segment(segment):
    """Clears a segment's pixels back to the atlas base color.

    Resets all pixels in the segment area to match the atlas's configured
    base color (black, white, or transparent).

    Args:
        segment: The YImageAtlasSegment to clear.
    """
    img = segment.id_data
    atlas = img.yia

    if atlas.color == "BLACK":
        col = (0.0, 0.0, 0.0, 1.0)
    elif atlas.color == "WHITE":
        col = (1.0, 1.0, 1.0, 1.0)
    else:
        col = (0.0, 0.0, 0.0, 0.0)

    set_image_pixels(img, col, segment)


def is_there_any_unused_segments(atlas, width, height):
    """Checks if there are any unused segments large enough for the requested dimensions.

    Searches through all segments in the atlas to find at least one that is marked
    as unused and has sufficient size.

    Args:
        atlas: The YImageAtlas property group to check.
        width (int): Minimum required width in pixels.
        height (int): Minimum required height in pixels.

    Returns:
        bool: True if at least one suitable unused segment exists, False otherwise.
    """
    for segment in atlas.segments:
        if segment.unused and segment.width >= width and segment.height >= height:
            return True
    return False


def get_entities_with_specific_segment(mp, segment):
    """Gets all layers and masks that are using a specific atlas segment.

    Searches through all layers and their masks in the MPaint data to find
    entities that reference the given segment.

    Args:
        mp: The MPaintPropertyGroup containing layer data.
        segment: The YImageAtlasSegment to search for.

    Returns:
        list: List of layer and mask entities using the segment.
    """

    entities = []

    layer_ids = get_layer_ids_with_specific_segment(mp, segment)
    for li in layer_ids:
        layer = mp.layers[li]
        entities.append(layer)

    for layer in mp.layers:
        masks = get_masks_with_specific_segment(layer, segment)
        entities.extend(masks)

    return entities


def get_segment_mapping(segment, image):
    """Calculates UV mapping parameters for a segment within an atlas.

    Computes the scale and offset values needed to map a segment's position
    within the atlas image to UV coordinates.

    Args:
        segment: The YImageAtlasSegment containing position and size data.
        image: The atlas Image containing the segment.

    Returns:
        tuple: (scale_x, scale_y, offset_x, offset_y) as float values for UV mapping.
    """

    scale_x = segment.width / image.size[0]
    scale_y = segment.height / image.size[1]

    offset_x = scale_x * segment.tile_x
    offset_y = scale_y * segment.tile_y

    return scale_x, scale_y, offset_x, offset_y
