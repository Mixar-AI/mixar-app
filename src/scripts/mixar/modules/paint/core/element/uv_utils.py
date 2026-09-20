# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
UV layer utility functions.

This module contains functions for working with UV layers, including
retrieving active UV layers, default UV names, and relevant UV layers
for painting context.
"""

from ...utils.blender_commons import get_bpy_data, remove_datablock
from ...utils.common import is_mask_using_vector
from ...utils.constants import TEMP_UV
from ..layer.layer_utils import get_uv_layers


def get_uv_layer_index(obj, uv_name):
    """
    Get the index of a UV layer by name.

    Parameters:
        obj: Blender object
        uv_name (str): Name of the UV layer

    Returns:
        int: Index of the UV layer, or -1 if not found
    """
    uv_layers = get_uv_layers(obj)
    for i, ul in enumerate(uv_layers):
        if ul.name == uv_name:
            return i

    return -1


def get_active_render_uv(obj):
    """
    Get the active render UV layer name.

    Returns the name of the UV layer marked as active for rendering,
    excluding temporary UV layers. If no active render UV is found,
    returns the first non-temporary UV layer.

    Parameters:
        obj: Blender object

    Returns:
        str: Name of the active render UV layer, or empty string if none found
    """
    uv_layers = get_uv_layers(obj)
    uv_name = ''

    if obj.type == 'MESH' and len(uv_layers) > 0:
        for uv_layer in uv_layers:
            if uv_layer.active_render and uv_layer.name != TEMP_UV:
                uv_name = uv_layer.name
                break

        if uv_name == '':
            for uv_layer in uv_layers:
                if uv_layer.name != TEMP_UV:
                    uv_name = uv_layer.name
                    break

    return uv_name


def get_default_uv_name(obj=None, mp=None):
    """
    Get the default UV layer name.

    Determines the default UV layer name from the active mesh object or creates
    a temporary mesh to get the default UV layer name used by Blender.

    Parameters:
        obj: Blender object. Default is None.
        mp: MPaint data. Default is None.

    Returns:
        str: Default UV layer name
    """
    uv_name = ''

    if obj and obj.type == 'MESH':

        # Get active uv name from active mesh object
        uv_layers = get_uv_layers(obj)
        if len(uv_layers) > 0:
            active_name = uv_layers.active.name
            if active_name == TEMP_UV:
                if mp and len(mp.layers) > 0:
                    uv_name = mp.layers[mp.active_layer_index].uv_name
                else:
                    for uv_layer in uv_layers:
                        if uv_layer.name != TEMP_UV:
                            uv_name = uv_layer.name
            else:
                uv_name = uv_layers.active.name

    else:
        # Create temporary mesh
        temp_mesh = get_bpy_data().meshes.new('___TEMP___')

        # Create temporary uv layer
        uv_layers = temp_mesh.uv_layers
        uv_layer = uv_layers.new()

        # Get the uv name
        uv_name = uv_layer.name

        # Remove temporary mesh
        remove_datablock(get_bpy_data().meshes, temp_mesh)

    return uv_name


def get_relevant_uv(obj, mp):
    """
    Get the relevant UV layer for the current painting context.

    Determines which UV layer should be used based on the active layer and mask,
    considering baked UV layers when applicable.

    Parameters:
        obj: Blender object
        mp: MPaint data

    Returns:
        str: Name of the relevant UV layer, or empty string if not found
    """
    try:
        layer = mp.layers[mp.active_layer_index]
    except:
        return ''

    uv_name = layer.baked_uv_name if layer.use_baked and layer.baked_uv_name != '' else layer.uv_name

    for mask in layer.masks:
        if mask.active_edit:
            if is_mask_using_vector(mask):
                uv_name = mask.baked_uv_name if mask.use_baked and mask.baked_uv_name != '' else mask.uv_name

    return uv_name


def get_correct_uv_neighbor_resolution(ch, image=None):
    """
    Get the correct UV neighbor resolution.

    Returns the image dimensions for UV neighbor calculations, using the image
    size if available or defaulting to 1000x1000.

    Parameters:
        ch: Channel object
        image: Blender image data. Default is None.

    Returns:
        tuple: (res_x, res_y) resolution in pixels
    """

    res_x = image.size[0] if image else 1000
    res_y = image.size[1] if image else 1000

    return res_x, res_y


def get_tilenums_height(tilenums):
    """
    Get the height (number of rows) of UDIM tiles.

    Calculates the vertical span of UDIM tiles by analyzing tile numbers.

    Parameters:
        tilenums: List or collection of UDIM tile numbers

    Returns:
        int: Number of rows the tiles span
    """
    min_y = int(min(tilenums) / 10)
    max_y = int(max(tilenums) / 10)

    return max_y - min_y + 1


def get_udim_segment_tiles_height(segment):
    """
    Get the height of tiles in a UDIM segment.

    Extracts tile numbers from a segment and calculates the vertical span.

    Parameters:
        segment: UDIM segment object containing base_tiles

    Returns:
        int: Number of rows the segment's tiles span
    """
    tilenums = [btile.number for btile in segment.base_tiles]
    return get_tilenums_height(tilenums)
