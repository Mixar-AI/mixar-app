# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image atlas and alpha baking functions for entity baking."""

from mixar.config.logging_config import get_logger

import bpy

from ....core.element.update_image import copy_image_channel_pixels, copy_image_pixels
from ....utils.blender_commons import get_noncolor_name, get_srgb_name, remove_datablock

from ...image_atlas.image_atlas_utils import (
    check_need_of_erasing_segments,
    clear_unused_segments,
    get_set_image_atlas_segment,
)
from ...udim.udim_utils import swap_tile
from ...udim.udim_utils_atlas import (
    copy_tiles,
    get_set_udim_atlas_segment,
    get_udim_segment_mapping_offset,
)
from ...udim.udim_utils_io import initial_pack_udim
from ...udim.udim_utils_segment import remove_udim_atlas_segment_by_name

from ..utils.bake_common import TEMP_EMISSION, fxaa_image

logger = get_logger(__name__)


def bake_other_object_alpha(image, tex, bprops, tilenums, scene, idx, ch_other_mats=None,
                            ch_other_alpha_defaults=None, ch_other_alpha_sockets=None,
                            other_mats=None, other_alpha_defaults=None, other_alpha_sockets=None):
    """Bake alpha channel for other object baking.

    Parameters:
        image: Target image
        tex: Texture node
        bprops: Bake properties
        tilenums: List of UDIM tile numbers
        scene: Blender scene
        idx: Channel index
        ch_other_mats: Channel other materials (for channels bake)
        ch_other_alpha_defaults: Channel alpha defaults
        ch_other_alpha_sockets: Channel alpha sockets
        other_mats: Other materials (for emission bake)
        other_alpha_defaults: Alpha defaults
        other_alpha_sockets: Alpha sockets
    """
    if bprops.type not in {
        "OTHER_OBJECT_NORMAL",
        "OTHER_OBJECT_CHANNELS",
        "OTHER_OBJECT_EMISSION",
    }:
        return

    alpha_found = _setup_alpha_emission(
        bprops, idx, ch_other_mats, ch_other_alpha_defaults,
        ch_other_alpha_sockets, other_mats, other_alpha_defaults, other_alpha_sockets
    )

    if alpha_found:
        _bake_alpha_image(image, tex, bprops, tilenums, scene)


def _setup_alpha_emission(bprops, idx, ch_other_mats, ch_other_alpha_defaults,
                          ch_other_alpha_sockets, other_mats, other_alpha_defaults,
                          other_alpha_sockets):
    """Setup emission nodes for alpha baking.

    Returns:
        bool: Whether alpha was found
    """
    alpha_found = False

    if bprops.type == "OTHER_OBJECT_CHANNELS" and ch_other_mats and ch_other_alpha_defaults and ch_other_alpha_sockets:
        for j, m in enumerate(ch_other_mats[idx]):
            alpha_default = ch_other_alpha_defaults[idx][j]
            alpha_socket = ch_other_alpha_sockets[idx][j]

            temp_emi = m.node_tree.nodes.get(TEMP_EMISSION)
            if not temp_emi:
                continue

            if alpha_socket:
                alpha_found = True
                m.node_tree.links.new(alpha_socket, temp_emi.inputs[0])
            else:
                if alpha_default != 1.0:
                    alpha_found = True

                if type(alpha_default) == float:
                    temp_emi.inputs[0].default_value = (
                        alpha_default, alpha_default, alpha_default, 1.0
                    )
                else:
                    temp_emi.inputs[0].default_value = (
                        alpha_default[0], alpha_default[1], alpha_default[2], 1.0
                    )

                for l in temp_emi.inputs[0].links:
                    m.node_tree.links.remove(l)

    elif bprops.type == "OTHER_OBJECT_EMISSION" and other_mats and other_alpha_defaults and other_alpha_sockets:
        for i, m in enumerate(other_mats):
            alpha_default = other_alpha_defaults[i]
            alpha_socket = other_alpha_sockets[i]

            temp_emi = m.node_tree.nodes.get(TEMP_EMISSION)
            if not temp_emi:
                continue

            if alpha_socket:
                alpha_found = True
                m.node_tree.links.new(alpha_socket, temp_emi.inputs[0])
            else:
                if alpha_default != 1.0:
                    alpha_found = True

                if type(alpha_default) == float:
                    temp_emi.inputs[0].default_value = (
                        alpha_default, alpha_default, alpha_default, 1.0
                    )
                else:
                    temp_emi.inputs[0].default_value = (
                        alpha_default[0], alpha_default[1], alpha_default[2], 1.0
                    )
    else:
        alpha_found = True

    return alpha_found


def _bake_alpha_image(image, tex, bprops, tilenums, scene):
    """Perform alpha baking and copy to main image."""
    temp_img = image.copy()
    temp_img.colorspace_settings.name = get_noncolor_name()
    tex.image = temp_img

    if image.source == "TILED":
        temp_img.name = "__TEMP__"
        initial_pack_udim(temp_img)

    scene.render.bake.use_clear = True
    bpy.ops.object.bake(type="EMIT")

    for tilenum in tilenums:
        if tilenum != 1001:
            swap_tile(image, 1001, tilenum)
            swap_tile(temp_img, 1001, tilenum)

        if bprops.type == "OTHER_OBJECT_NORMAL":
            copy_image_channel_pixels(temp_img, temp_img, 3, 0)

        fxaa_image(temp_img, False, bprops.bake_device, first_tile_only=True)
        copy_image_channel_pixels(temp_img, image, 0, 3)

        if tilenum != 1001:
            swap_tile(image, 1001, tilenum)
            swap_tile(temp_img, 1001, tilenum)

    remove_datablock(bpy.data.images, temp_img, user=tex, user_prop="image")


def handle_image_atlas(image, bprops, segment, tilenums, mp):
    """Handle image atlas operations.

    Parameters:
        image: Baked image
        bprops: Bake properties
        segment: Existing segment if any
        tilenums: List of UDIM tile numbers
        mp: Material properties

    Returns:
        tuple: (image, segment, new_segment_created)
    """
    if not bprops.use_image_atlas:
        return image, segment, False

    need_to_create_new_segment = _check_need_new_segment(bprops, segment, mp)

    if not segment or need_to_create_new_segment:
        segment = _create_new_segment(bprops, tilenums, mp)
        new_segment_created = True
    else:
        new_segment_created = False

    ia_image = segment.id_data

    # Set baked image to segment
    if bprops.use_udim:
        offset = get_udim_segment_mapping_offset(segment) * 10
        copy_dict = {}
        for tilenum in tilenums:
            copy_dict[tilenum] = tilenum + offset
        copy_tiles(image, ia_image, copy_dict)
    else:
        copy_image_pixels(image, ia_image, segment)

    temp_img = image
    image = ia_image

    # Remove original baked image
    remove_datablock(bpy.data.images, temp_img)

    return image, segment, new_segment_created


def _check_need_new_segment(bprops, segment, mp):
    """Check if a new segment needs to be created."""
    need_to_create_new_segment = False

    if segment:
        ia_image = segment.id_data
        if bprops.use_udim:
            need_to_create_new_segment = ia_image.is_float != bprops.hdr
            if need_to_create_new_segment:
                remove_udim_atlas_segment_by_name(ia_image, segment.name, mp)
        else:
            need_to_create_new_segment = (
                bprops.width != segment.width
                or bprops.height != segment.height
                or ia_image.is_float != bprops.hdr
            )
            if need_to_create_new_segment:
                segment.unused = True

    return need_to_create_new_segment


def _create_new_segment(bprops, tilenums, mp):
    """Create a new image atlas segment."""
    if bprops.use_udim:
        return get_set_udim_atlas_segment(
            tilenums,
            color=(0, 0, 0, 0),
            colorspace=get_srgb_name(),
            hdr=bprops.hdr,
            mp=mp,
        )
    else:
        img_atlas = check_need_of_erasing_segments(
            mp, "TRANSPARENT", bprops.width, bprops.height, bprops.hdr
        )
        if img_atlas:
            clear_unused_segments(img_atlas.yia)

        return get_set_image_atlas_segment(
            bprops.width, bprops.height, "TRANSPARENT", bprops.hdr, mp=mp
        )
