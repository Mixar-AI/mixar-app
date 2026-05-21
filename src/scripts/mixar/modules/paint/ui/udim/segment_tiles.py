# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UDIM tile operations for segment management."""

import os

import bpy

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from .udim_utils_io import (
    is_using_temp_dir,
    remove_udim_files_from_disk,
    save_udim,
    pack_udim,
)


def rearrange_tiles(image, convert_dict):
    """Rearrange UDIM tiles by renaming them according to conversion dictionary.

    Args:
        image: Blender image object containing tiles to rearrange.
        convert_dict (dict): Dictionary mapping old tile numbers to new tile numbers.

    Returns:
        None
    """

    # Directory of images
    directory = os.path.dirname(bpy.path.abspath(image.filepath))

    # Remember stuff
    ori_packed = False
    if image.packed_file:
        ori_packed = True

    # Image saved flag
    image_saved = False

    already_renamed = []

    # First pass of renaming
    for tilenum0, tilenum1 in convert_dict.items():

        tile = image.tiles.get(tilenum0)
        if not tile:
            continue

        # Get image paths
        str0 = "." + str(tilenum0) + "."
        str1 = "." + str(tilenum1) + "."
        filename = bpy.path.basename(image.filepath)
        splits = filename.split(".<UDIM>.")
        prefix = splits[0]
        suffix = splits[1]

        path0 = os.path.join(directory, prefix + str0 + suffix)
        path1 = os.path.join(directory, prefix + str1 + suffix)

        # Save the image first
        if not image_saved:
            save_udim(image)
            image_saved = True

        logger.info("UDIM: Rename tile %s to %s (%s)", tilenum0, tilenum1, image.name)

        # Copy and replace image
        if os.path.exists(path1):
            if tilenum1 in convert_dict:
                path1 += ".TEMP_NAME"
            else:
                os.remove(path1)

        # shutil.copyfile(path0, path1)
        os.rename(path0, path1)

    # Second pass is removing temporary name suffix
    if os.path.isdir(directory):

        temp_names = []
        ori_names = []

        for f in os.listdir(directory):
            if f.endswith(".TEMP_NAME"):
                temp_names.append(f)
                ori_names.append(f.split(".TEMP_NAME")[0])

        for i, temp_name in enumerate(temp_names):
            temp_path = os.path.join(directory, temp_name)
            ori_path = os.path.join(directory, ori_names[i])
            if os.path.exists(ori_path):
                os.remove(ori_path)
            os.rename(temp_path, ori_path)

    if image_saved:

        # Reload to update image
        image.reload()
        save_udim(image)

        # Repack image
        if ori_packed:
            pack_udim(image)

            # Remove file if they are using temporary directory
            if is_using_temp_dir(image):
                remove_udim_files_from_disk(image, directory, True)


def remove_tiles(image, tilenums):
    """Remove multiple UDIM tiles from image.

    Args:
        image: Blender image object to remove tiles from.
        tilenums (list): List of UDIM tile numbers to remove.

    Returns:
        None
    """

    # print('UDIM: Removing tiles is starting...')

    # Directory of image
    directory = os.path.dirname(bpy.path.abspath(image.filepath))

    # Remember stuff
    ori_packed = False
    if image.packed_file:
        ori_packed = True

    # Image saved flag
    image_saved = False

    for tilenum in tilenums:
        tile = image.tiles.get(tilenum)
        if not tile:
            continue

        # Save the image first
        if not image_saved:
            save_udim(image)
            image_saved = True

        logger.info("UDIM: Removing tile %s", tilenum)

        # Remove tile
        image.tiles.remove(tile)

    # Repack image
    if image_saved:
        if ori_packed:
            pack_udim(image)

            # Remove file if they are using temporary directory
            if is_using_temp_dir(image):
                remove_udim_files_from_disk(image, directory, True)
        else:
            # Remove file
            remove_udim_files_from_disk(image, directory, False, tilenum)
