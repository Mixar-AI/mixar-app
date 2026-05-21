# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bake execution and post-processing functions for entity baking."""

from mixar.config.logging_config import get_logger

import bpy

from ....core.element.update_image import copy_image_channel_pixels
from ....utils.blender_commons import (
    get_noncolor_name,
    remove_datablock,
)
from ...udim.udim_utils import swap_tile
from ...udim.udim_utils_io import initial_pack_udim

from .bake_common import (
    TEMP_EMISSION,
    denoise_image,
    fxaa_image,
    get_pointiness_image_minmax_value,
    resize_image,
)

logger = get_logger(__name__)


def execute_bake(bprops, bake_type, scene):
    """Execute the bake operation.

    Parameters:
        bprops: Bake properties
        bake_type: Type of bake to perform
        scene: Blender scene

    Returns:
        bool: True if successful
    """
    try:
        if bprops.type.startswith("MULTIRES_"):
            bpy.ops.object.bake_image()
        else:
            if bake_type != "EMIT":
                bpy.ops.object.bake(type=bake_type)
            else:
                bpy.ops.object.bake()
        return True
    except Exception as e:
        # Try to use CPU if GPU baking is failed
        if bprops.bake_device == "GPU":
            logger.warning("GPU baking failed! Trying to use CPU...")
            bprops.bake_device = "CPU"
            scene.cycles.device = "CPU"

            if bprops.type.startswith("MULTIRES_"):
                bpy.ops.object.bake_image()
            else:
                if bake_type != "EMIT":
                    bpy.ops.object.bake(type=bake_type)
                else:
                    bpy.ops.object.bake()
            return True
        else:
            logger.error("Baking exception: %s", e)
            return False


def post_process_image(image, bprops, use_fxaa, use_ssaa, use_denoise, map_range=None):
    """Apply post-processing to baked image.

    Parameters:
        image: Baked image
        bprops: Bake properties
        use_fxaa: Whether to apply FXAA
        use_ssaa: Whether to apply SSAA
        use_denoise: Whether to denoise
        map_range: Map range node for pointiness normalization

    Returns:
        Image: Processed image
    """
    if use_fxaa:
        fxaa_image(image, False, bake_device=bprops.bake_device)

    if bprops.type == "POINTINESS" and bprops.normalize and map_range:
        # Check for highest and lowest value of the baked image
        min_val, max_val = get_pointiness_image_minmax_value(image)

        # Set map range
        map_range.inputs[1].default_value = min_val
        map_range.inputs[2].default_value = max_val

        # Rebake the image again
        bpy.ops.object.bake(type="EMIT")

    # Back to original size if using SSAA
    if use_ssaa:
        image, temp_segment = resize_image(
            image,
            bprops.width,
            bprops.height,
            image.colorspace_settings.name,
            alpha_aware=True,
            bake_device=bprops.bake_device,
        )

    # Denoise AO image
    if use_denoise:
        image = denoise_image(image)

    return image


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

    alpha_found = False

    if bprops.type == "OTHER_OBJECT_CHANNELS" and ch_other_mats and ch_other_alpha_defaults and ch_other_alpha_sockets:
        # Set emission connection
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

                if isinstance(alpha_default, (float, int)):
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

                if isinstance(alpha_default, (float, int)):
                    temp_emi.inputs[0].default_value = (
                        alpha_default, alpha_default, alpha_default, 1.0
                    )
                else:
                    temp_emi.inputs[0].default_value = (
                        alpha_default[0], alpha_default[1], alpha_default[2], 1.0
                    )
    else:
        alpha_found = True

    if alpha_found:
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
