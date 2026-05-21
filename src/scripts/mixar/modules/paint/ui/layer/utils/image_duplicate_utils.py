# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image duplication utilities for layer duplication."""

import re

import bpy

from ....core.element.get_elements import get_image_mask_base_color
from ....core.layer.mappings import update_mapping
from ....utils.blender_commons import (
    duplicate_image,
    get_unique_name,
    get_user_preferences,
)
from ...image_atlas.image_atlas_utils import get_set_image_atlas_segment
from ...udim.udim_operators_helper import fill_tiles
from ...udim.udim_utils import (
    get_set_udim_atlas_segment,
    get_udim_segment_base_tilenums,
    get_udim_segment_tilenums,
    initial_pack_udim,
)


def duplicate_image_atlas(
    img, img_user, img_node, mp, mpup, duplicate_blank, specific_layers, copied_image_atlas
):
    """Handle duplication of image atlas segments.

    Args:
        img: Source image.
        img_user: User of the image (layer/mask/channel).
        img_node: Node containing the image.
        mp: Material properties.
        mpup: User preferences.
        duplicate_blank (bool): Create blank duplicate.
        specific_layers (list): List of specific layers being duplicated.
        copied_image_atlas (dict): Tracking dict for already copied atlases.

    Returns:
        bool: True if handled, False otherwise.
    """
    if not img.yia.is_image_atlas:
        return False

    segment = img.yia.segments.get(img_user.segment_name)
    new_segment = None

    # Create new segment based on previous one
    if duplicate_blank:
        new_segment = get_set_image_atlas_segment(
            segment.width, segment.height, img.yia.color, img.is_float, mp=mp
        )

    # If using different image atlas per mp, just copy the image (unless specific layer is on)
    elif mpup.unique_image_atlas_per_mp and not specific_layers:
        if img.name not in copied_image_atlas:
            copied_image_atlas[img.name] = duplicate_image(img)
        img_node.image = copied_image_atlas[img.name]

    else:
        new_segment = get_set_image_atlas_segment(
            segment.width,
            segment.height,
            img.yia.color,
            img.is_float,
            img,
            segment,
        )

    if new_segment:
        img_user.segment_name = new_segment.name

        # Change image if different image is returned
        if new_segment.id_data != img:
            img_node.image = new_segment.id_data

        # Update layer transform
        update_mapping(img_user)

    return True


def duplicate_udim_atlas(
    img, img_user, img_node, mp, duplicate_blank, specific_layers, copied_image_atlas
):
    """Handle duplication of UDIM atlas segments.

    Args:
        img: Source image.
        img_user: User of the image (layer/mask/channel).
        img_node: Node containing the image.
        mp: Material properties.
        duplicate_blank (bool): Create blank duplicate.
        specific_layers (list): List of specific layers being duplicated.
        copied_image_atlas (dict): Tracking dict for already copied atlases.

    Returns:
        bool: True if handled, False otherwise.
    """
    if not img.yua.is_udim_atlas:
        return False

    segment = img.yua.segments.get(img_user.segment_name)
    new_segment = None

    tilenums = get_udim_segment_base_tilenums(segment)
    segment_tilenums = get_udim_segment_tilenums(segment)

    # Create new segment based on previous one
    if duplicate_blank:
        new_segment = get_set_udim_atlas_segment(
            tilenums,
            color=img.yui.base_color,
            colorspace=img.colorspace_settings.name,
            hdr=img.is_float,
            mp=mp,
        )

    # If using different image atlas per mp, just copy the image (unless specific layer is on)
    elif not specific_layers:
        if img.name not in copied_image_atlas:
            copied_image_atlas[img.name] = duplicate_image(img)
        img_node.image = copied_image_atlas[img.name]

    else:
        new_segment = get_set_udim_atlas_segment(
            tilenums,
            color=img.yui.base_color,
            colorspace=img.colorspace_settings.name,
            hdr=img.is_float,
            mp=mp,
            source_image=img,
            source_tilenums=segment_tilenums,
        )

    if new_segment:
        img_user.segment_name = new_segment.name

        # Change image if different image is returned
        if new_segment.id_data != img:
            img_node.image = new_segment.id_data

        # Update layer transform
        update_mapping(img_user)

    return True


def duplicate_regular_image(img, img_user, img_node, duplicate_blank):
    """Handle duplication of regular (non-atlas) images.

    Args:
        img: Source image.
        img_user: User of the image (layer/mask/channel).
        img_node: Node containing the image.
        duplicate_blank (bool): Create blank duplicate.
    """
    if duplicate_blank:
        if hasattr(img, "use_alpha"):
            alpha = img.use_alpha
        else:
            alpha = True

        # Mask will have alpha filled
        m = re.match(
            r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", img_user.path_from_id()
        )
        if m:
            mask_idx = int(m.group(2))
            mask = img_user

            color = get_image_mask_base_color(mask, img, mask_idx)
        else:
            color = (0, 0, 0, 0)

        img_name = get_unique_name(img.name, bpy.data.images)

        if img.source == "TILED":
            img_node.image = img.copy()
            img_node.image.name = img_name
            fill_tiles(img_node.image, color)
            initial_pack_udim(img_node.image, color)
        else:
            img_node.image = bpy.data.images.new(
                img_name,
                width=img.size[0],
                height=img.size[1],
                alpha=alpha,
                float_buffer=img.is_float,
            )
            img_node.image.generated_color = color

        img_node.image.colorspace_settings.name = img.colorspace_settings.name

    else:
        img_node.image = duplicate_image(img)


def duplicate_images(
    mp,
    imgs,
    img_nodes,
    img_users,
    packed_duplicate=True,
    duplicate_blank=False,
    ondisk_duplicate=False,
    specific_layers=None,
):
    """Duplicate images for layers and masks.

    Args:
        mp: Material properties object.
        imgs (list): List of images to duplicate.
        img_nodes (list): List of nodes using images.
        img_users (list): List of layer/mask users of images.
        packed_duplicate (bool, optional): Duplicate packed images. Defaults to True.
        duplicate_blank (bool, optional): Create blank duplicates. Defaults to False.
        ondisk_duplicate (bool, optional): Duplicate on-disk images. Defaults to False.
        specific_layers (list, optional): Specific layers to duplicate. Defaults to None.
    """
    if specific_layers is None:
        specific_layers = []

    mpup = get_user_preferences()
    already_copied_ids = []
    copied_image_atlas = {}

    for i, img in enumerate(imgs):
        # Check if it's an ondisk image
        if not img.packed_file and img.filepath != "":
            if not ondisk_duplicate:
                continue
        # Or packed image
        elif not packed_duplicate:
            continue

        # Try image atlas first
        if duplicate_image_atlas(
            img, img_users[i], img_nodes[i], mp, mpup,
            duplicate_blank, specific_layers, copied_image_atlas
        ):
            continue

        # Try UDIM atlas
        if duplicate_udim_atlas(
            img, img_users[i], img_nodes[i], mp,
            duplicate_blank, specific_layers, copied_image_atlas
        ):
            continue

        # Regular image
        if i not in already_copied_ids:
            duplicate_regular_image(img, img_users[i], img_nodes[i], duplicate_blank)

            # Check other nodes using the same image
            for j, imgg in enumerate(imgs):
                if j != i and imgg == img:
                    img_nodes[j].image = img_nodes[i].image
                    already_copied_ids.append(j)
