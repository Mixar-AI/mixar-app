# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for bake target operations."""

from mixar.config.logging_config import get_logger

import bpy

from ....core.element.update_image import copy_image_channel_pixels, replace_image, set_image_pixels
from ....core.node.create_nodes import check_new_node
from ...udim.udim_operators_helper import fill_tile
from ...udim.udim_utils import initial_pack_udim, swap_tile
from ....utils.blender_commons import get_noncolor_name

logger = get_logger(__name__)

# Channel letters for RGBA
rgba_letters = ["r", "g", "b", "a"]


def process_custom_bake_targets(
    mp, tree, channels, tilenums, width, height, use_udim
):
    """Process custom bake target images.

    Args:
        mp: Material properties
        tree: Node tree
        channels: List of channels
        tilenums: List of tile numbers
        width: Target width
        height: Target height
        use_udim: Whether using UDIM
    """
    for bt in mp.bake_targets:
        logger.info("Processing custom bake target '%s'...", bt.name)
        bt_node = tree.nodes.get(bt.image_node)
        btimg = bt_node.image if bt_node and bt_node.image else None

        old_img = None
        filepath = ""
        if btimg and (
            btimg.size[0] != width
            or btimg.size[1] != height
            or (btimg.source == "TILED" and not use_udim)
            or (btimg.source != "TILED" and use_udim)
        ):
            old_img = btimg
            btimg = None
            if (old_img.source == "TILED" and use_udim) or (
                old_img.source != "TILED" and not use_udim
            ):
                filepath = old_img.filepath

        # Get default colors
        color = _get_bake_target_default_colors(bt, channels)

        if not btimg:
            btimg = _create_bake_target_image(
                bt, tilenums, width, height, color, filepath
            )
        else:
            _fill_existing_bake_target(btimg, tilenums, color)

        # Copy image channels
        _copy_bake_target_channels(bt, btimg, channels, tree, tilenums)

        # Set bake target image
        if old_img:
            replace_image(old_img, btimg)
        else:
            bt_node = check_new_node(
                tree, bt, "image_node", "ShaderNodeTexImage"
            )
            bt_node.image = btimg


def _get_bake_target_default_colors(bt, channels):
    """Get default colors for a bake target.

    Args:
        bt: Bake target
        channels: List of channels

    Returns:
        List of RGBA color values
    """
    color = []
    for letter in rgba_letters:
        btc = getattr(bt, letter)
        ch = [
            c
            for c in channels
            if c.name == (getattr(btc, "channel_name"))
        ]
        if ch:
            ch = ch[0]
        if ch and ch.type == "NORMAL":
            if btc.normal_type in {"COMBINED", "OVERLAY_ONLY"}:
                # Normal RG default value
                if btc.subchannel_index in {"0", "1"}:
                    color.append(0.5)
                else:
                    # Normal BA default value
                    color.append(1.0)
            else:
                # Displacement default value
                color.append(0.5)
        else:
            color.append(btc.default_value)
    return color


def _create_bake_target_image(bt, tilenums, width, height, color, filepath):
    """Create a new bake target image.

    Args:
        bt: Bake target
        tilenums: List of tile numbers
        width: Image width
        height: Image height
        color: Default color
        filepath: File path for the image

    Returns:
        The created image
    """
    if len(tilenums) > 1:
        btimg = bpy.data.images.new(
            name=bt.name,
            width=width,
            height=height,
            alpha=True,
            tiled=True,
            float_buffer=bt.use_float,
        )
        btimg.colorspace_settings.name = get_noncolor_name()
        btimg.filepath = filepath

        # Fill tiles
        for tilenum in tilenums:
            fill_tile(btimg, tilenum, color, width, height)

        initial_pack_udim(btimg, color)
    else:
        btimg = bpy.data.images.new(
            name=bt.name,
            width=width,
            height=height,
            alpha=True,
            float_buffer=bt.use_float,
        )
        btimg.colorspace_settings.name = get_noncolor_name()
        btimg.filepath = filepath
        btimg.generated_color = color
    return btimg


def _fill_existing_bake_target(btimg, tilenums, color):
    """Fill existing bake target image with color.

    Args:
        btimg: Bake target image
        tilenums: List of tile numbers
        color: Color to fill with
    """
    for tilenum in tilenums:

        # Swap tile
        if tilenum != 1001:
            swap_tile(btimg, 1001, tilenum)

        # Only set image color if image is already found
        set_image_pixels(btimg, color)

        # Swap tile again to recover
        if tilenum != 1001:
            swap_tile(btimg, 1001, tilenum)


def _copy_bake_target_channels(bt, btimg, channels, tree, tilenums):
    """Copy baked channels to bake target image.

    Args:
        bt: Bake target
        btimg: Bake target image
        channels: List of channels
        tree: Node tree
        tilenums: List of tile numbers
    """
    for i, letter in enumerate(rgba_letters):
        btc = getattr(bt, letter)
        ch = [
            c
            for c in channels
            if c.name == (getattr(btc, "channel_name"))
        ]
        if ch:
            ch = ch[0]

            # Get image channel
            subidx = 0
            if ch.type in {"RGB", "NORMAL"}:
                subidx = int(getattr(btc, "subchannel_index"))

            # Get baked node
            baked = None
            if ch.type == "NORMAL" and btc.normal_type == "OVERLAY_ONLY":
                baked = tree.nodes.get(ch.baked_normal_overlay)
            elif ch.type == "NORMAL" and btc.normal_type == "DISPLACEMENT":
                baked = tree.nodes.get(ch.baked_disp)
                subidx = 0
            elif (
                ch.type == "NORMAL"
                and btc.normal_type == "VECTOR_DISPLACEMENT"
            ):
                baked = tree.nodes.get(ch.baked_vdisp)
            else:
                baked = tree.nodes.get(ch.baked)

            if baked and baked.image:
                for tilenum in tilenums:
                    # Swap tile
                    if tilenum != 1001:
                        swap_tile(btimg, 1001, tilenum)
                        swap_tile(baked.image, 1001, tilenum)

                    # Copy pixels
                    copy_image_channel_pixels(
                        baked.image,
                        btimg,
                        src_idx=subidx,
                        dest_idx=i,
                        invert_value=btc.invert_value,
                    )

                    # Swap tile again to recover
                    if tilenum != 1001:
                        swap_tile(btimg, 1001, tilenum)
                        swap_tile(baked.image, 1001, tilenum)
