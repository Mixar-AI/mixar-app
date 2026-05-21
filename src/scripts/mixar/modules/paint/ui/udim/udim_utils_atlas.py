# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UDIM atlas creation and management functions."""

import os
import re
import shutil

import bpy
import numpy

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.layer.get_entities import get_mp_entities_using_same_image, get_mp_images
from ...core.layer.mappings import (
    get_layer_mapping,
    get_mask_mapping,
    get_udim_segment_mapping_offset,
)
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...core.node.get_nodes import get_entity_source
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_unique_name,
    get_user_preferences,
    is_image_filepath_unique,
)

# Import from io module to avoid circular import
from .udim_utils_io import (
    fill_tile,
    initial_pack_udim,
    is_using_temp_dir,
    pack_udim,
    remove_udim_files_from_disk,
    save_udim,
)

def get_set_udim_atlas_segment(
    tilenums,
    width=1024,
    height=1024,
    color=(0, 0, 0, 0),
    colorspace="",
    hdr=False,
    mp=None,
    source_image=None,
    source_tilenums=[],
    image_exception=None,
    image_inclusions=[],
):
    """Get existing or create new UDIM atlas segment for given tile numbers.

    Args:
        tilenums (list): List of UDIM tile numbers to allocate.
        width (int, optional): Tile width in pixels. Defaults to 1024.
        height (int, optional): Tile height in pixels. Defaults to 1024.
        color (tuple, optional): RGBA base color. Defaults to (0, 0, 0, 0).
        colorspace (str, optional): Colorspace name. Defaults to "".
        hdr (bool, optional): If True, use HDR/float buffer. Defaults to False.
        mp (PropertyGroup, optional): MPaint property group. Defaults to None.
        source_image: Source image to copy from. Defaults to None.
        source_tilenums (list, optional): Source tile numbers to copy. Defaults to [].
        image_exception: Image to exclude from search. Defaults to None.
        image_inclusions (list, optional): Additional images to include in search. Defaults to [].

    Returns:
        PropertyGroup: UDIM atlas segment that was found or created.
    """

    mpup = get_user_preferences()
    segment = None

    # Get bunch of images
    if mp:  # and mpup.unique_image_atlas_per_mp:
        images = get_mp_images(mp, udim_only=True)
        name = mp.id_data.name
    else:
        images = [img for img in bpy.data.images if img.source == "TILED"]
        name = ""

    # Extra images to be included
    for image in image_inclusions:
        if image not in images:
            images.append(image)

    for image in images:
        if image_exception and image == image_exception:
            continue
        if (
            image.yua.is_udim_atlas
            and image.is_float == hdr
            and is_tilenums_fit_in_udim_atlas(image, tilenums)
        ):
            if colorspace != "" and image.colorspace_settings.name != colorspace:
                continue
            segment = create_udim_atlas_segment(
                image,
                tilenums,
                width,
                height,
                color,
                source_image=source_image,
                source_tilenums=source_tilenums,
                mp=mp,
            )
        if segment:
            break

    if not segment:
        # If proper UDIM atlas can't be found, create new one
        image = create_udim_atlas(tilenums, name, width, height, color, colorspace, hdr)
        segment = create_udim_atlas_segment(
            image,
            tilenums,
            width,
            height,
            color,
            source_image=source_image,
            source_tilenums=source_tilenums,
            mp=mp,
        )

    return segment


def is_tilenums_fit_in_udim_atlas(image, tilenums):
    """Check if tile numbers can fit in existing UDIM atlas.

    Args:
        image: Blender image object (UDIM atlas) to check.
        tilenums (list): List of UDIM tile numbers to check.

    Returns:
        bool: True if tile numbers fit within available atlas space, False otherwise.
    """
    max_y = int((max(tilenums) - 1000) / 10)
    atlas_tilenums = [t.number for t in image.tiles]
    if len(atlas_tilenums) > 0:
        atlas_max_y = int((max(atlas_tilenums) - 1000) / 10) + 1
    else:
        atlas_max_y = 0

    remains_y = 99 - atlas_max_y

    return remains_y > max_y


def create_udim_atlas_segment(
    image,
    tilenums,
    width=1024,
    height=1024,
    color=(0, 0, 0, 0),
    source_image=None,
    source_tilenums=[],
    mp=None,
):
    """Create a new segment in an existing UDIM atlas.

    Args:
        image: Blender image object (UDIM atlas) to add segment to.
        tilenums (list): List of base UDIM tile numbers for the segment.
        width (int, optional): Tile width in pixels. Defaults to 1024.
        height (int, optional): Tile height in pixels. Defaults to 1024.
        color (tuple, optional): RGBA base color. Defaults to (0, 0, 0, 0).
        source_image: Source image to copy tiles from. Defaults to None.
        source_tilenums (list, optional): Source tile numbers to copy. Defaults to [].
        mp (PropertyGroup, optional): MPaint property group. Defaults to None.

    Returns:
        PropertyGroup: The created UDIM atlas segment.
    """

    # if mp: refresh_udim_atlas(image, mp)

    # Make sure filepath is not empty
    if image.filepath == "":
        initial_pack_udim(image)

    atlas = image.yua
    name = get_unique_name("Segment", atlas.segments)

    segment = None

    segment = atlas.segments.add()
    segment.name = name
    segment.base_color = color
    refresh_udim_segment_base_tilenums(segment, tilenums)
    offset = get_udim_segment_mapping_offset(segment) * 10

    copy_dict = {}

    for i, tilenum in enumerate(tilenums):
        if source_image:
            if source_tilenums != []:
                source_tile = source_image.tiles.get(source_tilenums[i])
            else:
                source_tile = source_image.tiles.get(tilenum)
            width = source_tile.size[0]
            height = source_tile.size[1]
            if source_tilenums != []:
                copy_dict[source_tilenums[i]] = tilenum + offset
            else:
                copy_dict[tilenum] = tilenum + offset

        tilenum += offset
        fill_tile(image, tilenum, color, width, height, empty_only=False)

    # Copy from source image
    if source_image:
        copy_tiles(source_image, image, copy_dict)

    # Pack image
    initial_pack_udim(image, force_temp_dir=True)

    return segment


def create_udim_atlas(
    tilenums,
    name="",
    width=1024,
    height=1024,
    color=(0, 0, 0, 0),
    colorspace="",
    hdr=False,
):
    """Create a new UDIM atlas image.

    Args:
        tilenums (list): List of UDIM tile numbers to determine atlas size.
        name (str, optional): Base name for the atlas. Defaults to "".
        width (int, optional): Tile width in pixels. Defaults to 1024.
        height (int, optional): Tile height in pixels. Defaults to 1024.
        color (tuple, optional): RGBA base color. Defaults to (0, 0, 0, 0).
        colorspace (str, optional): Colorspace name. Defaults to "".
        hdr (bool, optional): If True, use HDR/float buffer. Defaults to False.

    Returns:
        Image: The created UDIM atlas image object.
    """
    if name != "":
        name = "~" + name + " UDIM Atlas"
    else:
        name = "~UDIM Atlas"

    # Get offset based on max y value
    max_y = int((max(tilenums) - 1000) / 10)
    offset_y = max_y + 2

    name = get_unique_name(name, bpy.data.images)

    image = bpy.data.images.new(
        name=name, width=width, height=height, alpha=True, float_buffer=hdr, tiled=True
    )
    image.yua.is_udim_atlas = True
    image.yui.base_color = color

    # Float image atlas always use premultipled alpha
    if hdr:
        image.alpha_mode = "PREMUL"

    # Pack image
    initial_pack_udim(image)

    # Set colorspace
    if colorspace != "" and image.colorspace_settings.name != colorspace:
        image.colorspace_settings.name = colorspace

    return image


def refresh_udim_segment_base_tilenums(segment, tilenums):
    """Update segment's base tile numbers to match provided list.

    Args:
        segment (PropertyGroup): UDIM atlas segment to update.
        tilenums (list): List of UDIM tile numbers to set as base tiles.

    Returns:
        None
    """
    # Add tiles
    for tilenum in tilenums:
        if str(tilenum) not in segment.base_tiles:
            btile = segment.base_tiles.add()
            btile.name = str(tilenum)
            btile.number = tilenum

    # Remove unused tiles
    for i, btile in reversed(list(enumerate(segment.base_tiles))):
        if btile.number not in tilenums:
            segment.base_tiles.remove(i)


def copy_tiles(image0, image1, copy_dict):
    """Copy tiles from one UDIM image to another according to mapping.

    Args:
        image0: Source Blender image object.
        image1: Destination Blender image object.
        copy_dict (dict): Dictionary mapping source tile numbers to destination tile numbers.

    Returns:
        None
    """

    # Directory of images
    directory0 = os.path.dirname(bpy.path.abspath(image0.filepath))
    directory1 = os.path.dirname(bpy.path.abspath(image1.filepath))

    # Remember stuff
    ori0_packed = False
    ori1_packed = False
    if image0.packed_file:
        ori0_packed = True
    if image1.packed_file:
        ori1_packed = True

    # Image saved flag
    image_saved = False

    for tilenum0, tilenum1 in copy_dict.items():

        tile0 = image0.tiles.get(tilenum0)
        tile1 = image1.tiles.get(tilenum1)

        if not tile0 or not tile1:
            continue

        # Get image paths
        str0 = "." + str(tilenum0) + "."
        str1 = "." + str(tilenum1) + "."
        filename0 = bpy.path.basename(image0.filepath)
        filename1 = bpy.path.basename(image1.filepath)
        splits0 = filename0.split(".<UDIM>.")
        splits1 = filename1.split(".<UDIM>.")
        prefix0 = splits0[0]
        prefix1 = splits1[0]
        suffix0 = splits0[1]
        suffix1 = splits1[1]

        path0 = os.path.join(directory0, prefix0 + str0 + suffix0)
        path1 = os.path.join(directory1, prefix1 + str1 + suffix1)

        if suffix0 != suffix1:
            continue
        if path0 == path1:
            continue

        # Save the image first
        if not image_saved:
            save_udim(image0)
            save_udim(image1)
            image_saved = True

        logger.info(
            "UDIM: Copying tile %s (%s) to %s (%s)",
            tilenum0, image0.name, tilenum1, image1.name
        )

        # Copy and replace image
        if os.path.exists(path1):
            os.remove(path1)
        shutil.copyfile(path0, path1)

    if image_saved:

        # Reload to update image
        # image0.reload()
        image1.reload()
        # save_udim(image0)
        save_udim(image1)

        # Repack image 0
        if ori0_packed:
            pack_udim(image0)

        # Repack image 1
        if ori1_packed:
            pack_udim(image1)

        if ori0_packed:
            # Remove file if they are using temporary directory
            if is_using_temp_dir(image0):
                remove_udim_files_from_disk(image0, directory0, True)

        if ori1_packed:
            # Remove file if they are using temporary directory
            if is_using_temp_dir(image1):
                remove_udim_files_from_disk(image1, directory1, True)


