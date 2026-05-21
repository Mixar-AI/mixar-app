# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

import bpy
from ..udim.udim_utils import remove_udim_atlas_segment_by_name, set_udim_segment_mapping
from ...core.element.update_image import copy_image_pixels

from ...core.layer.get_entities import get_mp_images
from ...core.layer.mappings import clear_mapping, get_layer_mapping, get_mask_mapping
from ...core.node.get_nodes import get_entity_source
from ...utils.blender_commons import (
    get_noncolor_name,
    get_unique_name,
    get_user_preferences,
)
from ..image_atlas.image_atlas_operators_helper import (
    clear_segment,
    get_available_tile,
    get_entities_with_specific_segment,
    get_segment_mapping,
    is_there_any_unused_segments,
)

def clear_unused_segments(atlas):
    """Removes all unused segments from an image atlas.

    Clears the pixels of unused segments to the atlas base color, then removes
    them from the segments collection.

    Args:
        atlas: The YImageAtlas property group containing segments to clean up.
    """

    # Recolor unused segments
    for segment in atlas.segments:
        if segment.unused:
            clear_segment(segment)

    # Remove unused segments
    for i, segment in reversed(list(enumerate(atlas.segments))):
        if segment.unused:
            atlas.segments.remove(i)


def check_need_of_erasing_segments(
    mp, color="BLACK", width=1024, height=1024, hdr=False
):
    """Checks if any image atlas needs to erase unused segments to make room.

    Searches through image atlases matching the specified criteria to find one that
    is full but has unused segments that could be cleared to make space.

    Args:
        mp: The MPaintPropertyGroup containing layer data.
        color (str, optional): Atlas base color ("BLACK", "WHITE", or "TRANSPARENT"). Defaults to "BLACK".
        width (int, optional): Required segment width in pixels. Defaults to 1024.
        height (int, optional): Required segment height in pixels. Defaults to 1024.
        hdr (bool, optional): Whether to search for HDR (float buffer) atlases. Defaults to False.

    Returns:
        Image or None: The image atlas that needs cleanup, or None if no cleanup is needed.
    """

    ypup = get_user_preferences()
    images = get_mp_images(mp) if ypup.unique_image_atlas_per_mp else bpy.data.images

    for img in images:
        # if img.yia.is_image_atlas and img.yia.color == color and img.yia.float_buffer == hdr:
        if img.yia.is_image_atlas and img.yia.color == color and img.is_float == hdr:
            if not get_available_tile(
                width, height, img.yia
            ) and is_there_any_unused_segments(img.yia, width, height):
                return img

    return None


def replace_segment_with_image(mp, segment, image, uv_name=""):
    """Replaces an atlas segment with a standard image for all entities using it.

    Updates all entities (layers/masks) that reference the specified segment to use
    a standard image instead, clears their mapping data, and marks the segment as unused.

    Args:
        mp: The MPaintPropertyGroup containing layer data.
        segment: The YImageAtlasSegment to replace.
        image: The standard Blender Image to use as replacement.
        uv_name (str, optional): UV map name to assign to entities. Defaults to "".

    Returns:
        list: List of entities that were updated.
    """

    entities = get_entities_with_specific_segment(mp, segment)

    for entity in entities:
        # Replace image
        source = get_entity_source(entity)
        source.image = image
        entity.segment_name = ""

        # Clear mapping and set new uv map
        clear_mapping(entity)
        if uv_name != "" and entity.uv_name != uv_name:
            entity.uv_name = uv_name

    # Remove segment
    if segment.id_data.source == "TILED":
        remove_udim_atlas_segment_by_name(segment.id_data, segment.name, mp)
    else:
        # Make segment unused
        segment.unused = True

    return entities


def set_segment_mapping(entity, segment, image, use_baked=False):
    """Sets UV mapping for an entity to display the correct atlas segment.

    Calculates and applies the scale and offset values needed to map a segment
    within an atlas image to the entity's UV coordinates.

    Args:
        entity: The layer or mask entity to update.
        segment: The YImageAtlasSegment containing position data.
        image: The atlas Image containing the segment.
        use_baked (bool, optional): Whether to use baked mapping. Defaults to False.
    """

    if image.source == "TILED":
        set_udim_segment_mapping(entity, segment, image, use_baked)
        return

    scale_x, scale_y, offset_x, offset_y = get_segment_mapping(segment, image)

    m1 = re.match(r"^mp\.layers\[(\d+)\]$", entity.path_from_id())
    m2 = re.match(r"^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$", entity.path_from_id())

    if m1:
        mapping = get_layer_mapping(entity, get_baked=use_baked)
    else:
        mapping = get_mask_mapping(entity, get_baked=use_baked)

    if mapping:
        mapping.inputs[3].default_value[0] = scale_x
        mapping.inputs[3].default_value[1] = scale_y

        mapping.inputs[1].default_value[0] = offset_x
        mapping.inputs[1].default_value[1] = offset_y


def get_set_image_atlas_segment(
    width, height, color="BLACK", hdr=False, img_from=None, segment_from=None, mp=None
):
    """Gets an existing or creates a new image atlas segment with specified dimensions.

    Searches for an available atlas matching the criteria, creates a segment in it,
    or creates a new atlas if necessary. Optionally copies pixel data from another segment.

    Args:
        width (int): Width of the segment in pixels.
        height (int): Height of the segment in pixels.
        color (str, optional): Atlas base color ("BLACK", "WHITE", or "TRANSPARENT"). Defaults to "BLACK".
        hdr (bool, optional): Whether to use HDR (float buffer) atlas. Defaults to False.
        img_from (Image, optional): Source image to copy pixels from. Defaults to None.
        segment_from (YImageAtlasSegment, optional): Source segment to copy pixels from. Defaults to None.
        mp (MPaintPropertyGroup, optional): The MPaint data for unique atlas per material. Defaults to None.

    Returns:
        YImageAtlasSegment: The created or found segment.
    """

    ypup = get_user_preferences()
    segment = None

    # Get bunch of images
    if mp and ypup.unique_image_atlas_per_mp:
        images = get_mp_images(mp)
        name = mp.id_data.name
    else:
        images = bpy.data.images
        name = ""

    # Search for available image atlas
    for img in images:
        # if img.yia.is_image_atlas and img.yia.color == color and img.yia.float_buffer == hdr:
        if img.yia.is_image_atlas and img.yia.color == color and img.is_float == hdr:
            segment = create_image_atlas_segment(img.yia, width, height)
            if segment:
                # return segment
                break
            else:
                # This is where unused segments should be erased
                pass

    if not segment:
        if hdr:
            new_atlas_size = ypup.hdr_image_atlas_size
        else:
            new_atlas_size = ypup.image_atlas_size

        # If proper image atlas can't be found, create new one
        img = create_image_atlas(color, new_atlas_size, hdr, name)
        segment = create_image_atlas_segment(img.yia, width, height)
        # if segment: return segment

    if img_from and segment_from:
        copy_image_pixels(img_from, img, segment, segment_from)

    return segment




def create_image_atlas(color="BLACK", size=8192, hdr=False, name=""):
    """Creates a new image atlas with the specified properties.

    Creates a square Blender Image configured as an image atlas with the appropriate
    color space and alpha settings based on the color type and HDR flag.

    Args:
        color (str, optional): Base color ("BLACK", "WHITE", or "TRANSPARENT"). Defaults to "BLACK".
        size (int, optional): Width and height of the atlas in pixels. Defaults to 8192.
        hdr (bool, optional): Whether to create HDR (float buffer) atlas. Defaults to False.
        name (str, optional): Base name for the atlas (will be prefixed with ~). Defaults to "".

    Returns:
        Image: The created Blender Image configured as an atlas.
    """

    if name != "":
        name = "~" + name + " Image Atlas"
    else:
        name = "~Image Atlas"

    if hdr:
        name += " HDR"

    name = get_unique_name(name, bpy.data.images)

    img = bpy.data.images.new(
        name=name, width=size, height=size, alpha=True, float_buffer=hdr
    )

    if color == "BLACK":
        img.generated_color = (0, 0, 0, 1)
        img.colorspace_settings.name = get_noncolor_name()
    elif color == "WHITE":
        img.generated_color = (1, 1, 1, 1)
        img.colorspace_settings.name = get_noncolor_name()
    else:  # TRANSPARENT
        img.generated_color = (0, 0, 0, 0)
        img.colorspace_settings.name = get_noncolor_name()

    img.yia.is_image_atlas = True
    img.yia.color = color
    # img.yia.float_buffer = hdr

    # Float image atlas always use premultiplied alpha
    if hdr:
        # img.colorspace_settings.name = get_noncolor_name()
        img.alpha_mode = "PREMUL"

    return img



def create_image_atlas_segment(atlas, width, height):
    """Creates a new segment in an image atlas if space is available.

    Searches for an available tile position that can fit the requested dimensions
    and creates a new segment at that location.

    Args:
        atlas: The YImageAtlas property group to add the segment to.
        width (int): Width of the segment in pixels.
        height (int): Height of the segment in pixels.

    Returns:
        YImageAtlasSegment or None: The created segment, or None if no space available.
    """

    name = get_unique_name("Segment", atlas.segments)

    segment = None

    tile = get_available_tile(width, height, atlas)
    if tile:
        segment = atlas.segments.add()
        segment.name = name
        segment.width = width
        segment.height = height
        segment.tile_x = tile[0]
        segment.tile_y = tile[1]

    return segment
