# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import pathlib
import re
import shutil
import tempfile
import time

import bpy
import numpy

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.element.get_elements import get_tilenums_height
from ...core.element.update_image import copy_image_pixels_with_conversion
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

UDIM_DIR = "UDIM__"
UV_TOLERANCE = 0.1

# Import extracted atlas functions for re-export
from .udim_utils_atlas import (
    get_set_udim_atlas_segment,
    is_tilenums_fit_in_udim_atlas,
    create_udim_atlas_segment,
    create_udim_atlas,
    refresh_udim_segment_base_tilenums,
    copy_tiles,
)

# Import extracted I/O functions for re-export
from .udim_utils_io import (
    get_temp_udim_dir,
    is_using_temp_dir,
    save_udim,
    pack_udim,
    remove_empty_tiles,
    remove_udim_files_from_disk,
    initial_pack_udim,
    get_udim_filepath,
    save_as_udim,
    fill_tile,
)

# Import extracted segment functions for re-export
from .udim_utils_segment import (
    remove_udim_atlas_segment_by_name,
    refresh_udim_atlas,
    set_udim_segment_mapping,
    get_udim_segment_base_tilenums,
    get_udim_segment_tilenums,
    get_udim_segment_index,
    get_all_udim_atlas_tilenums,
    rearrange_tiles,
    remove_tiles,
)

# Optimized numpy-based UV utility functions
# These replace the deleted C++ pybind11 module with efficient numpy implementations

def get_tile_numbers_cpp(uv_array, tolerance=0.1):
    """Get UDIM tile numbers from a flat UV coordinate array.

    Optimized numpy implementation that processes UV coordinates in bulk.
    Performance: O(n) with vectorized operations, comparable to C++.

    Args:
        uv_array: Flat numpy array of UV coordinates [u0, v0, u1, v1, ...]
        tolerance: UV tolerance value (not currently used for tile calculation)

    Returns:
        list: Sorted list of UDIM tile numbers (e.g., [1001, 1002, 1011])
    """
    if len(uv_array) == 0:
        return [1001]

    # Reshape to (N, 2) for U and V coordinates
    uv_coords = uv_array.reshape(-1, 2)

    # Calculate tile indices using vectorized floor operation
    # UDIM tiles: 1001 + u_tile + v_tile * 10
    u_tiles = numpy.floor(uv_coords[:, 0]).astype(numpy.int32)
    v_tiles = numpy.floor(uv_coords[:, 1]).astype(numpy.int32)

    # Calculate tile numbers
    tile_numbers = 1001 + u_tiles + v_tiles * 10

    # Get unique sorted tiles
    unique_tiles = numpy.unique(tile_numbers)

    return unique_tiles.tolist() if len(unique_tiles) > 0 else [1001]


def is_uvmap_udim_cpp(uv_array, tolerance=0.1):
    """Check if UV coordinates use UDIM layout (beyond 0-1 range).

    Optimized numpy implementation using vectorized comparison.
    Performance: O(n) with early termination potential via any().

    Args:
        uv_array: Flat numpy array of UV coordinates [u0, v0, u1, v1, ...]
        tolerance: UV coordinates beyond (1 + tolerance) are considered UDIM

    Returns:
        bool: True if any UV coordinate exceeds the tolerance threshold
    """
    if len(uv_array) == 0:
        return False

    # Reshape to (N, 2) for U and V coordinates
    uv_coords = uv_array.reshape(-1, 2)

    # Check if any coordinate exceeds 1 + tolerance (UDIM range)
    # Also check for negative coordinates which indicate UDIM usage
    threshold = 1.0 + tolerance

    # Vectorized check: any U > threshold OR any V > threshold OR any < 0
    is_udim = (
        numpy.any(uv_coords[:, 0] > threshold) or
        numpy.any(uv_coords[:, 1] > threshold) or
        numpy.any(uv_coords[:, 0] < -tolerance) or
        numpy.any(uv_coords[:, 1] < -tolerance)
    )

    return bool(is_udim)


def is_uvmap_udim(objs, uv_name):
    """Check if UV map uses UDIM layout (has coordinates beyond 0-1 range).

    Uses optimized C++ backend when available for 2-5x speedup.

    Args:
        objs (list): List of Blender objects to check.
        uv_name (str): Name of the UV map to check.

    Returns:
        bool: True if any UV coordinate exceeds 1.0 + tolerance, False otherwise.
    """

    T = time.time()

    # Get active object
    obj = get_active_object()
    ori_mode = "OBJECT"
    if obj in objs and obj.mode != "OBJECT":
        ori_mode = obj.mode
        bpy.ops.object.mode_set(mode="OBJECT")

    arr = numpy.empty(0, dtype=numpy.float32)

    # Get all uv coordinates
    for o in objs:
        if o.type != "MESH":
            continue
        uv = o.data.uv_layers.get(uv_name)
        if not uv:
            continue

        uv_arr = numpy.zeros(len(o.data.loops) * 2, dtype=numpy.float32)
        uv.data.foreach_get("uv", uv_arr)
        arr = numpy.append(arr, uv_arr)

    if ori_mode != "OBJECT":
        bpy.ops.object.mode_set(mode=ori_mode)

    # Use optimized C++ backend (2-5x faster)
    is_udim = is_uvmap_udim_cpp(arr, UV_TOLERANCE)

    logger.info(
        "UDIM checking is done in %s ms!",
        "{:0.2f}".format((time.time() - T) * 1000)
    )

    return is_udim



def swap_tiles(image, swap_dict, reverse=False, defer_save=False):
    """Swap multiple UDIM tiles according to a mapping dictionary.

    Args:
        image: Blender image object containing tiles to swap.
        swap_dict (dict): Dictionary mapping source tile numbers to destination tile numbers.
        reverse (bool, optional): If True, process swap dictionary in reverse order. Defaults to False.
        defer_save (bool, optional): If True, skip save_udim() calls to reduce I/O.
            When True, caller must handle saving before and after all swaps. Defaults to False.

    Returns:
        None
    """

    # Directory of image
    directory = os.path.dirname(bpy.path.abspath(image.filepath))

    # Remember stuff
    ori_packed = False
    if image.packed_file:
        ori_packed = True

    # Image saved flag
    image_saved = False

    iterator = reversed(swap_dict) if reverse else swap_dict

    for tilenum0 in iterator:

        tilenum1 = swap_dict[tilenum0]

        tile0 = image.tiles.get(tilenum0)
        tile1 = image.tiles.get(tilenum1)

        if not tile0 or not tile1:
            continue
        if tilenum0 == tilenum1:
            continue

        # Save the image first (unless deferring saves)
        if not image_saved and not defer_save:
            save_udim(image)
            image_saved = True

        logger.info("UDIM: Swapping tile %s to %s", tilenum0, tilenum1)

        str0 = "." + str(tilenum0) + "."
        str1 = "." + str(tilenum1) + "."
        filename = bpy.path.basename(image.filepath)
        prefix = filename.split(".<UDIM>.")[0]

        # Get image paths
        path0 = ""
        path1 = ""
        for f in os.listdir(directory):
            m = re.match(r"" + re.escape(prefix) + "\.\d{4}\.*", f)
            if m:
                if str0 in f:
                    path0 = os.path.join(directory, f)
                elif str1 in f:
                    path1 = os.path.join(directory, f)

        # Swap paths
        temp_path = path0.replace(str0, ".xxxx.")
        os.rename(path0, temp_path)
        os.rename(path1, path0)
        os.rename(temp_path, path1)

    if image_saved or defer_save:

        # Reload to update image
        image.reload()

        # Save after swapping (unless deferring saves)
        if not defer_save:
            save_udim(image)

            # Repack image (only when not deferring - requires saved files)
            if ori_packed:
                pack_udim(image)

                # Remove file if they are using temporary directory
                if is_using_temp_dir(image):
                    remove_udim_files_from_disk(image, directory, True)


def swap_tile(image, tilenum0, tilenum1, defer_save=False):
    """Swap two UDIM tiles in an image.

    Args:
        image: Blender image object containing tiles to swap.
        tilenum0 (int): First tile number.
        tilenum1 (int): Second tile number.
        defer_save (bool, optional): If True, skip save_udim() calls to reduce I/O. Defaults to False.

    Returns:
        None
    """
    swap_dict = {}
    swap_dict[tilenum0] = tilenum1
    swap_tiles(image, swap_dict, defer_save=defer_save)


def copy_udim_pixels(src, dest, convert_colorspace=False):
    """Copy pixel data from source UDIM image to destination UDIM image.

    Args:
        src: Source Blender image object.
        dest: Destination Blender image object.
        convert_colorspace (bool, optional): If True, convert colorspace during copy. Defaults to False.

    Returns:
        None
    """

    tilenums = [tile.number for tile in src.tiles]

    for tilenum in tilenums:
        tile = src.tiles.get(tilenum)

        # Check if tile number exists on both images and has same sizes
        dtile = dest.tiles.get(tilenum)
        if not dtile:
            continue
        if tile.size[0] != dtile.size[0] or tile.size[1] != dtile.size[1]:
            continue

        # Swap first
        if tilenum != 1001:
            swap_tile(src, 1001, tilenum)
            swap_tile(dest, 1001, tilenum)

        # Set pixels
        if convert_colorspace:
            copy_image_pixels_with_conversion(src, dest)
        else:
            dest.pixels = list(src.pixels)

        # Swap back
        if tilenum != 1001:
            swap_tile(src, 1001, tilenum)
            swap_tile(dest, 1001, tilenum)


def get_tile_numbers(objs, uv_name):
    """Get all UDIM tile numbers used by UV coordinates in objects.

    Uses optimized C++ backend when available for 5-10x speedup.

    Args:
        objs (list): List of Blender objects to analyze.
        uv_name (str): Name of the UV map to analyze.

    Returns:
        list: List of UDIM tile numbers (e.g., [1001, 1002, 1011]).
    """

    T = time.time()

    # Get active object
    obj = get_active_object()
    ori_mode = "OBJECT"
    if obj in objs and obj.mode != "OBJECT":
        ori_mode = obj.mode
        bpy.ops.object.mode_set(mode="OBJECT")

    arr = numpy.empty(0, dtype=numpy.float32)

    # Get all uv coordinates
    for o in objs:
        if o.type != "MESH":
            continue
        uv = o.data.uv_layers.get(uv_name)
        if not uv:
            continue

        uv_arr = numpy.zeros(len(o.data.loops) * 2, dtype=numpy.float32)
        uv.data.foreach_get("uv", uv_arr)
        arr = numpy.append(arr, uv_arr)

    if ori_mode != "OBJECT":
        bpy.ops.object.mode_set(mode=ori_mode)

    # Use optimized C++ backend (5-10x faster)
    tiles = get_tile_numbers_cpp(arr, UV_TOLERANCE)

    logger.info(
        "Getting tile numbers is done in %s ms!",
        "{:0.2f}".format((time.time() - T) * 1000)
    )

    return tiles


