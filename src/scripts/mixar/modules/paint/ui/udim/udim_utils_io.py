# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UDIM file I/O and packing operations."""

import os
import pathlib
import re
import tempfile

import bpy

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...utils.blender_commons import is_image_filepath_unique


def get_temp_udim_dir():
    """Get temporary directory for UDIM operations.

    Returns:
        str: Path to temporary UDIM directory, creating it if necessary.
    """
    path = os.path.join(tempfile.gettempdir(), "UDIM__")
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def is_using_temp_dir(image):
    """Check if image is using temporary directory for storage.

    Args:
        image: Blender image object to check.

    Returns:
        bool: True if image filepath is in temp directory, False otherwise.
    """
    if image.filepath == "":
        return False

    temp_dir = get_temp_udim_dir()

    directory = os.path.dirname(bpy.path.abspath(image.filepath))
    if directory.startswith(temp_dir):
        return True

    return False


def save_udim(image):
    """Save UDIM image to disk.

    Args:
        image: Blender image object to save.

    Returns:
        None
    """
    override = bpy.context.copy()
    override["edit_image"] = image
    with bpy.context.temp_override(**override):
        bpy.ops.image.save_as(
            filepath=bpy.path.abspath(image.filepath), relative_path=True
        )


def pack_udim(image):
    """Pack UDIM image into blend file, removing empty tiles first.

    Args:
        image: Blender image object to pack.

    Returns:
        None
    """

    # NOTE: Empty tiles can cause error with packing, so there's a need to remove them
    if remove_empty_tiles(image):

        # Save udim first before packing the image
        if image.filepath != "":
            save_udim(image)

    image.pack()


def remove_empty_tiles(image):
    """Remove all empty tiles (tiles with 0 channels) from UDIM image.

    Args:
        image: Blender image object to remove empty tiles from.

    Returns:
        bool: True if any empty tiles were removed, False otherwise.
    """
    empties_removed = False

    # Check if there's empty tiles
    empty_numbers = []
    for tile in image.tiles:
        if tile.channels == 0:
            empty_numbers.append(tile.number)

    # Remove if there's empty tiles
    if len(empty_numbers) > 0:

        for number in empty_numbers:
            tile = image.tiles.get(number)
            if tile and tile.number == number:
                image.tiles.remove(tile)

        if len(image.tiles) > 0:
            image.tiles.active = image.tiles[-1]

        empties_removed = True

    return empties_removed


def remove_udim_files_from_disk(image, directory, remove_dir=False, tilenum=-1):
    """Remove UDIM tile files from disk.

    Args:
        image: Blender image object whose files to remove.
        directory (str): Directory path containing UDIM files.
        remove_dir (bool, optional): If True, remove empty parent directories. Defaults to False.
        tilenum (int, optional): Specific tile number to remove, or -1 for all. Defaults to -1.

    Returns:
        None
    """
    # Get filenames
    img_names = []
    filename = bpy.path.basename(image.filepath)
    prefix = filename.split(".<UDIM>.")[0]
    if os.path.isdir(directory):
        for f in os.listdir(directory):
            m = re.match(r"" + re.escape(prefix) + "\.(\d{4})\.*", f)
            if m:
                if tilenum != -1 and tilenum != int(m.group(1)):
                    continue
                img_names.append(f)

    # Remove images
    for f in img_names:
        try:
            os.remove(os.path.join(directory, f))
        except Exception as e:
            logger.error(e)

    # Remove directory with all the empty parents
    if remove_dir and directory != tempfile.gettempdir():
        cur_dir = pathlib.Path(directory)
        while True:

            # Only remove when the directory is empty
            if os.path.isdir(cur_dir) and len(os.listdir(cur_dir)) == 0:
                try:
                    os.rmdir(cur_dir)
                except Exception as e:
                    logger.error(e)

            # Get the parent
            parent_dir = cur_dir.parent

            # Break if parent is not empty
            if parent_dir == cur_dir or (
                os.path.isdir(parent_dir) and len(os.listdir(parent_dir)) > 0
            ):
                break

            # Set current path to parent path
            cur_dir = parent_dir


def initial_pack_udim(image, base_color=None, filename="", force_temp_dir=False):
    """Initialize and pack UDIM image, setting up filepath and base color.

    Args:
        image: Blender image object to initialize and pack.
        base_color (tuple, optional): RGBA base color to remember. Defaults to None.
        filename (str, optional): Custom filename. Defaults to "" (uses image name).
        force_temp_dir (bool, optional): Force use of temporary directory. Defaults to False.

    Returns:
        None
    """

    # Get temporary directory
    temp_dir = get_temp_udim_dir()

    # Check if image is already packed
    use_packed = False
    if image.packed_file:
        use_packed = True

    # Check if image already use temporary filepath
    use_temp_dir = is_using_temp_dir(image)

    # Set temporary filepath
    filepath = image.filepath
    directory = os.path.dirname(bpy.path.abspath(filepath))

    if (
        filepath == ""  # Set image filepath if it's still empty
        or not is_image_filepath_unique(
            filepath
        )  # Force set new filepath when image filepath is not unique
        or (force_temp_dir and bpy.data.filepath != "")  # Force temporary directory
        or (
            not use_temp_dir and not os.path.isdir(directory)
        )  # When blend file is copied to another PC, there's a chance directory is missing
    ):
        filename = filename if filename != "" else image.name

        # Get temp filepath
        filepath = get_udim_filepath(filename, temp_dir)
        use_temp_dir = True

    # Save then pack
    save_as_udim(image, filepath)

    if use_packed or use_temp_dir:
        pack_udim(image)

    # Remove temporary files
    if use_temp_dir:
        remove_udim_files_from_disk(image, temp_dir, True)

    # Remember base color
    if base_color:
        image.yui.base_color = base_color


def get_udim_filepath(filename, directory):
    """Generate UDIM filepath with proper format.

    Args:
        filename (str): Base filename without extension.
        directory (str): Directory path for the file.

    Returns:
        str: Full filepath with UDIM placeholder (e.g., "filename.<UDIM>.png").
    """
    filepath = os.path.join(directory, filename + ".<UDIM>.png")
    if directory != tempfile.gettempdir():
        try:
            filepath = bpy.path.relpath(filepath)
        except:
            pass
    # if not os.path.exists(directory):
    #    os.makedirs(directory)
    return filepath


def save_as_udim(image, filepath=""):
    """Save UDIM image to a specific filepath.

    Args:
        image: Blender image object to save.
        filepath (str, optional): Target filepath. Defaults to "" (uses image's current filepath).

    Returns:
        None
    """
    if filepath == "":
        filepath = image.filepath
    override = bpy.context.copy()
    override["edit_image"] = image
    with bpy.context.temp_override(**override):
        bpy.ops.image.save_as(filepath=bpy.path.abspath(filepath), relative_path=True)


def fill_tile(image, tilenum, color=None, width=0, height=0, empty_only=False):
    """Fill or create a specific UDIM tile with color.

    Args:
        image: Blender image object to fill tile in.
        tilenum (int): UDIM tile number to fill.
        color (tuple, optional): RGBA color tuple (0-1 range). Defaults to None (uses image base color).
        width (int, optional): Tile width in pixels. Defaults to 0 (uses existing or 1024).
        height (int, optional): Tile height in pixels. Defaults to 0 (uses existing or 1024).
        empty_only (bool, optional): If True, only fill if tile doesn't exist or is empty. Defaults to False.

    Returns:
        bool: True if tile was filled/created, False otherwise.
    """
    if image.source != "TILED":
        return False
    if color is None:
        color = image.yui.base_color
    tile = image.tiles.get(tilenum)

    if width == 0:
        width = image.size[0]
    if height == 0:
        height = image.size[1]
    if width == 0:
        width = 1024
    if height == 0:
        height = 1024

    # HACK: For some reason 1001 tile is always exists when using get
    # Check if it actually exists by comparing the returned tile number
    if not tile or tile.number != tilenum:
        # Create new tile
        override = bpy.context.copy()
        override["edit_image"] = image
        with bpy.context.temp_override(**override):
            bpy.ops.image.tile_add(
                number=tilenum,
                count=1,
                label="",
                color=color,
                width=width,
                height=height,
                float=image.is_float,
                alpha=True,
            )

    # HACK: UDIM image with size of 0 always need to be filled first
    elif not empty_only or (tilenum == 1001 and image.size[0] == 0):

        image.tiles.active = tile

        override = bpy.context.copy()
        override["edit_image"] = image
        with bpy.context.temp_override(**override):
            bpy.ops.image.tile_fill(
                color=color,
                width=width,
                height=height,
                float=image.is_float,
                alpha=True,
            )

    else:
        return False

    color_str = "("
    color_str += str(color[0]) + ", "
    color_str += str(color[1]) + ", "
    color_str += str(color[2]) + ", "
    color_str += str(color[3]) + ")"

    logger.info("UDIM: Filling tile %s with color %s", tilenum, color_str)

    return True
