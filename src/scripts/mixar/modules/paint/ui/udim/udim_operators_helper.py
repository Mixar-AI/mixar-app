# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy

from ...core.node.node_utils import get_active_mpaint_node
from .udim_utils import fill_tile, remove_tiles, remove_udim_atlas_segment_by_name


def fill_tiles(image, color=None, width=0, height=0, empty_only=False):
    """Fill all tiles in a UDIM image with specified color.

    Args:
        image: Blender image object to fill tiles in.
        color (tuple, optional): RGBA color tuple (0-1 range). Defaults to None (uses image base color).
        width (int, optional): Tile width in pixels. Defaults to 0 (uses existing).
        height (int, optional): Tile height in pixels. Defaults to 0 (uses existing).
        empty_only (bool, optional): If True, only fill empty tiles. Defaults to False.

    Returns:
        None
    """
    if image.source != "TILED":
        return
    if color is None:
        color = image.yui.base_color
    for tile in image.tiles:
        fill_tile(image, tile.number, color, width, height, empty_only)


def remove_tile(image, tilenum):
    """Remove a single UDIM tile from an image.

    Args:
        image: Blender image object to remove tile from.
        tilenum (int): UDIM tile number to remove.

    Returns:
        None
    """
    remove_tiles(image, [tilenum])


def remove_udim_atlas_segment_by_index(image, index, mp=None):
    """Remove a UDIM atlas segment by its index.

    Args:
        image: Blender image object containing the UDIM atlas.
        index (int): Index of the segment to remove.
        mp (PropertyGroup, optional): MPaint property group. Defaults to None (retrieves from active node).

    Returns:
        None
    """
    if not mp:
        mp = get_active_mpaint_node().node_tree.mp
    try:
        segment = image.yua.segments[index]
    except:
        return
    remove_udim_atlas_segment_by_name(image, segment.name, mp)
