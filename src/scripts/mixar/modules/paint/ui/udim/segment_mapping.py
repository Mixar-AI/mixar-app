# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UDIM segment mapping and tile number utilities."""

import re

from ...core.layer.mappings import (
    get_layer_mapping,
    get_mask_mapping,
    get_udim_segment_mapping_offset,
)


def set_udim_segment_mapping(entity, segment, image, use_baked=False):
    """Set UV mapping offset for entity to match UDIM segment position.

    Args:
        entity (PropertyGroup): Layer or mask entity to update.
        segment (PropertyGroup): UDIM atlas segment.
        image: Blender image object containing the segment.
        use_baked (bool, optional): If True, update baked mapping instead. Defaults to False.

    Returns:
        None
    """

    offset_y = get_udim_segment_mapping_offset(segment)

    m1 = re.match(r"^mp\.layers\[(\d+)\]$", entity.path_from_id())
    m2 = re.match(r"^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$", entity.path_from_id())

    if m1:
        mapping = get_layer_mapping(entity, get_baked=use_baked)
    else:
        mapping = get_mask_mapping(entity, get_baked=use_baked)

    if mapping:
        mapping.inputs[1].default_value[1] = offset_y


def get_udim_segment_base_tilenums(segment):
    """Get list of base tile numbers from a UDIM segment.

    Args:
        segment (PropertyGroup): UDIM atlas segment.

    Returns:
        list: List of base UDIM tile numbers.
    """
    return [btile.number for btile in segment.base_tiles]


def get_udim_segment_tilenums(segment):
    """Get actual tile numbers used by segment in atlas (base tiles + offset).

    Args:
        segment (PropertyGroup): UDIM atlas segment.

    Returns:
        list: List of actual UDIM tile numbers in the atlas.
    """

    image = segment.id_data
    offset_y = get_udim_segment_mapping_offset(segment)

    tilenums = []
    for btile in segment.base_tiles:
        tilenum = btile.number + offset_y * 10
        tilenums.append(tilenum)

    return tilenums


def get_udim_segment_index(image, segment):
    """Get index of segment in UDIM atlas.

    Args:
        image: Blender image object (UDIM atlas).
        segment (PropertyGroup): UDIM atlas segment to find.

    Returns:
        int: Index of segment in atlas, or -1 if not found.
    """
    index = -1
    ids = [i for i, s in enumerate(image.yua.segments) if s == segment]
    if len(ids) > 0:
        index = ids[0]
    return index


def get_all_udim_atlas_tilenums(image, tilenums=[]):
    """Get all tile numbers used by all segments in UDIM atlas.

    Args:
        image: Blender image object (UDIM atlas).
        tilenums (list, optional): Unused parameter. Defaults to [].

    Returns:
        list: List of all UDIM tile numbers used across all segments.
    """

    all_tilenums = []

    for segment in image.yua.segments:
        tilenums = get_udim_segment_tilenums(segment)
        all_tilenums.extend(tilenums)

    return all_tilenums
