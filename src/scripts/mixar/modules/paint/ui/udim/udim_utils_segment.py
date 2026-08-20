# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UDIM atlas segment management and tile operations."""

import time

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.get_elements import get_tilenums_height
from ...core.layer.get_entities import get_mp_entities_using_same_image
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...core.node.get_nodes import get_entity_source
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import get_active_material

# Import from io module to avoid circular import
from .udim_utils_io import (
    fill_tile,
    initial_pack_udim,
    is_using_temp_dir,
)

# Import from atlas module
from .udim_utils_atlas import (
    get_set_udim_atlas_segment,
    refresh_udim_segment_base_tilenums,
)

# Import from segment_mapping module
from .segment_mapping import (
    set_udim_segment_mapping,
    get_udim_segment_base_tilenums,
    get_udim_segment_tilenums,
    get_udim_segment_index,
    get_all_udim_atlas_tilenums,
)

# Import from segment_tiles module
from .segment_tiles import (
    rearrange_tiles,
    remove_tiles,
)


def _get_tile_numbers():
    """Lazy import to avoid circular dependency."""
    from .udim_utils import get_tile_numbers
    return get_tile_numbers


def remove_udim_atlas_segment_by_name(image, segment_name, mp=None):
    """Remove a UDIM atlas segment by its name.

    Args:
        image: Blender image object containing the UDIM atlas.
        segment_name (str): Name of the segment to remove.
        mp (PropertyGroup, optional): MPaint property group. Defaults to None (retrieves from active node).

    Returns:
        None
    """
    T = time.time()

    if not mp:
        mp = get_active_mpaint_node().node_tree.mp

    index = [i for i, s in enumerate(image.yua.segments) if s.name == segment_name]
    if len(index) == 0:
        return
    index = index[0]

    refresh_udim_atlas(image, mp, check_uv=False, remove_index=index)

    logger.info(
        "UDIM Atlas segment is removed in %s ms!",
        "{:0.2f}".format((time.time() - T) * 1000)
    )


def refresh_udim_atlas(image, mp=None, check_uv=True, remove_index=-1):
    """Refresh UDIM atlas by updating tile offsets and reorganizing segments.

    Args:
        image: Blender image object (UDIM atlas) to refresh.
        mp (PropertyGroup, optional): MPaint property group. Defaults to None (retrieves from active node).
        check_uv (bool, optional): If True, check UV coordinates to update tile numbers. Defaults to True.
        remove_index (int, optional): Index of segment to remove, or -1 for none. Defaults to -1.

    Returns:
        Image: The refreshed UDIM atlas image.
    """
    T = time.time()

    # Actual tilenums from the image
    cur_tilenums = [t.number for t in image.tiles]

    if not mp:
        mp = get_active_mpaint_node().node_tree.mp

    entities = get_mp_entities_using_same_image(mp, image)

    # Create conversion dict
    convert_dict = {}
    uv_tilenums_dict = {}
    new_tilenums_dict = {}
    out_of_bound_segment_names = []

    ori_offset_y = 0
    new_offset_y = 0
    for i, segment in enumerate(image.yua.segments):

        # Get original base tilenums
        ori_tilenums = new_tilenums = get_udim_segment_base_tilenums(segment)

        # Get UV name
        if check_uv:
            uv_name = ""
            ents = [ent for ent in entities if ent.segment_name == segment.name]
            if ents:
                uv_name = ents[0].uv_name

            if uv_name == "":
                ents = [
                    ent for ent in entities if ent.baked_segment_name == segment.name
                ]
                if ents:
                    uv_name = (
                        ents[0].uv_name
                        if ents[0].baked_uv_name == ""
                        else ents[0].baked_uv_name
                    )

            # Get new tilenums based on uv
            if uv_name != "":
                if uv_name not in uv_tilenums_dict:
                    mat = get_active_material()
                    objs = get_all_objects_with_same_materials(mat, True, uv_name)
                    new_tilenums = uv_tilenums_dict[uv_name] = _get_tile_numbers()(
                        objs, uv_name
                    )
                else:
                    new_tilenums = uv_tilenums_dict[uv_name]

        # Remember new tilenums
        new_tilenums_dict[segment.name] = new_tilenums

        # Skip for to be removed index
        if i != remove_index:

            # Fill conversion dict
            tile_convert_dict = {}
            out_of_bound = False
            for nt in new_tilenums:
                new_index = nt + new_offset_y * 10
                if new_index > 2000:
                    out_of_bound = True
                else:
                    if nt in ori_tilenums:
                        ori_index = nt + ori_offset_y * 10
                        if ori_index != new_index:
                            tile_convert_dict[ori_index] = new_index

            if out_of_bound:
                out_of_bound_segment_names.append(segment.name)
            else:
                convert_dict.update(tile_convert_dict)

        # Add tilenums height to original offset
        ori_offset_y += get_tilenums_height(ori_tilenums) + 1

        # Skip for to be removed index
        if i != remove_index:

            # Add tilenums height to new offset
            new_offset_y += get_tilenums_height(new_tilenums) + 1

    # If there are out of bound segments, create new segments
    oob_dict = {}
    new_atlas_images = []
    for name in out_of_bound_segment_names:
        segment = image.yua.segments.get(name)
        segment_base_tilenums = get_udim_segment_base_tilenums(segment)
        segment_tilenums = get_udim_segment_tilenums(segment)
        new_segment = get_set_udim_atlas_segment(
            segment_base_tilenums,
            color=segment.base_color,
            colorspace=image.colorspace_settings.name,
            hdr=image.is_float,
            mp=mp,
            source_image=image,
            source_tilenums=segment_tilenums,
            image_exception=image,
            image_inclusions=new_atlas_images,
        )

        oob_dict[name] = new_segment
        if new_segment.id_data not in new_atlas_images:
            new_atlas_images.append(new_segment.id_data)

    # Remove out of bound segments
    for name in out_of_bound_segment_names:
        segment = image.yua.segments.get(name)
        index = get_udim_segment_index(image, segment)
        image.yua.segments.remove(index)

    # If remove index exists
    if remove_index != -1:
        image.yua.segments.remove(remove_index)

    # Set new tilenums
    for segment in image.yua.segments:
        new_tilenums = new_tilenums_dict[segment.name]
        refresh_udim_segment_base_tilenums(segment, new_tilenums)

        # Check for out of bounds segments
        # segment_tilenums = get_udim_segment_tilenums(segment)

    # Extend tilenums
    tilenums = get_all_udim_atlas_tilenums(image)

    # Fill tiles
    dirty = False
    for tilenum in tilenums:
        if fill_tile(image, tilenum, empty_only=True):
            dirty = True

    # Pack after fill
    if dirty or image.filepath == "" or not is_using_temp_dir(image):
        initial_pack_udim(image, force_temp_dir=True)

    # Rearrange tiles
    rearrange_tiles(image, convert_dict)

    # Fill tiles again in case there's empty tiles
    dirty = False
    for tilenum in tilenums:
        if fill_tile(image, tilenum, empty_only=True):
            dirty = True

    # Pack after fill again once more
    if dirty or image.filepath == "" or not is_using_temp_dir(image):
        initial_pack_udim(image, force_temp_dir=True)

    # Remove unused tilenum
    unused_tilenums = [
        tile.number
        for tile in image.tiles
        if tile.number not in tilenums and tile.number != 1001
    ]
    remove_tiles(image, unused_tilenums)

    # Refresh entities mapping
    for entity in entities:
        if entity.segment_name != "":
            if entity.segment_name in oob_dict:
                # Set entity that are using newly create segment on other image
                source = get_entity_source(entity)
                source.image = new_segment.id_data
                entity.segment_name = new_segment.name
                set_udim_segment_mapping(entity, new_segment, new_segment.id_data)
            else:
                segment = image.yua.segments.get(entity.segment_name)
                if segment:
                    set_udim_segment_mapping(entity, segment, image)

        if entity.baked_segment_name != "":
            if entity.baked_segment_name in oob_dict:
                # Set entity that are using newly create segment on other image
                source = get_entity_source(entity, get_baked=True)
                source.image = new_segment.id_data
                entity.baked_segment_name = new_segment.name
                set_udim_segment_mapping(
                    entity, new_segment, new_segment.id_data, use_baked=True
                )
            else:
                segment = image.yua.segments.get(entity.baked_segment_name)
                if segment:
                    set_udim_segment_mapping(entity, segment, image, use_baked=True)

    # Also refresh newly created atlas images
    for new_image in new_atlas_images:
        refresh_udim_atlas(
            new_image, mp=mp, check_uv=check_uv, remove_index=remove_index
        )

    logger.info(
        "UDIM Atlas offsets are refreshed in %s ms!",
        "{:0.2f}".format((time.time() - T) * 1000)
    )

    return image


# Re-export all functions for backward compatibility
__all__ = [
    # From this module
    "remove_udim_atlas_segment_by_name",
    "refresh_udim_atlas",
    # From segment_mapping
    "set_udim_segment_mapping",
    "get_udim_segment_base_tilenums",
    "get_udim_segment_tilenums",
    "get_udim_segment_index",
    "get_all_udim_atlas_tilenums",
    # From segment_tiles
    "rearrange_tiles",
    "remove_tiles",
]
