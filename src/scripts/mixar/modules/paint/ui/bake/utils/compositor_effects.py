# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compositor-based image processing effects for baking.

This module contains image processing functions that use Blender's compositor
for effects like blur, denoise, and dither.
"""

from mixar.config.logging_config import get_logger

import os
import tempfile
import time

import bpy

from ....core.element.update_image import (
    copy_image_channel_pixels,
    copy_image_pixels,
)
from ....utils.blender_commons import (
    get_srgb_name,
    is_bl_newer_than,
    remove_datablock,
)
from ...udim.udim_utils import swap_tile
from ...udim.udim_utils_io import pack_udim, save_udim
from .bake_scene_settings import (
    get_compositor_node_tree,
    get_compositor_output_node,
)
from .bake_settings_manager import (
    prepare_composite_settings,
    recover_composite_settings,
)

logger = get_logger(__name__)


def blur_image(image, filter_type="GAUSS", size=10):
    """Apply blur effect to an image using compositor.

    Args:
        image: Blender image object to blur.
        filter_type (str, optional): Type of blur filter. Defaults to "GAUSS".
        size (int, optional): Blur size in pixels. Defaults to 10.

    Returns:
        Image: The blurred image object.
    """
    T = time.time()
    logger.info("BLUR: Doing Blur pass on %s...", image.name)

    # Preparing settings
    book = prepare_composite_settings(use_hdr=image.is_float)

    # Get window context and temp scene
    window_ctx = book.get("window_ctx")
    temp_scene = bpy.data.scenes.get(book['temp_scene_name'])

    # Create context override with temp scene
    if window_ctx:
        ctx_override = window_ctx.copy()
        ctx_override['scene'] = temp_scene
    else:
        ctx_override = {'scene': temp_scene}

    # Work within the temp scene context
    with bpy.context.temp_override(**ctx_override):
        scene = bpy.context.scene

        # Set up compositor
        tree = get_compositor_node_tree(scene)
        composite = get_compositor_output_node(tree)
        blur = tree.nodes.new("CompositorNodeBlur")
        blur.filter_type = filter_type
        if is_bl_newer_than(4, 5):
            blur.inputs["Size"].default_value[0] = size
            blur.inputs["Size"].default_value[1] = size
        else:
            blur.size_x = int(size)
            blur.size_y = int(size)
        image_node = tree.nodes.new("CompositorNodeImage")
        image_node.image = image

        gamma = None
        if image.colorspace_settings.name != get_srgb_name() and not image.is_float:
            nodeid = "ShaderNodeGamma" if is_bl_newer_than(5) else "CompositorNodeGamma"
            gamma = tree.nodes.new(nodeid)
            gamma.inputs[1].default_value = 2.2

        rgb = image_node.outputs[0]
        if gamma:
            tree.links.new(rgb, gamma.inputs[0])
            rgb = gamma.outputs[0]
        tree.links.new(rgb, blur.inputs["Image"])
        rgb = blur.outputs[0]
        tree.links.new(rgb, composite.inputs[0])

        if image.source == "TILED":
            tilenums = [tile.number for tile in image.tiles]
        else:
            tilenums = [1001]

        # Save once before processing all tiles (Optimization: defer_save)
        if image.source == "TILED":
            save_udim(image)

        try:
            for tilenum in tilenums:

                # Swap tile to 1001 to access the data (defer saves for performance)
                if tilenum != 1001:
                    swap_tile(image, 1001, tilenum, defer_save=True)

                # Set render resolution
                scene.render.resolution_x = image.size[0]
                scene.render.resolution_y = image.size[1]

                # Render image (already in correct context)
                bpy.ops.render.render()

                # Copy pixels directly from render result (no temp file I/O)
                render_result = next(
                    img for img in bpy.data.images if img.type == "RENDER_RESULT"
                )
                copy_image_pixels(render_result, image)

                # Swap back the tile (defer saves for performance)
                if tilenum != 1001:
                    swap_tile(image, 1001, tilenum, defer_save=True)
        finally:
            # Ensure final save always happens
            if image.source == "TILED":
                save_udim(image)
                # Repack if image was originally packed
                if image.packed_file:
                    pack_udim(image)

    # Recover settings
    recover_composite_settings(book)

    logger.info(
        "BLUR: %s blur pass is done in %s seconds!",
        image.name,
        "{:0.2f}".format(time.time() - T),
    )
    return image


def denoise_image(image):
    """Apply denoising effect to an image using compositor.

    Args:
        image: Blender image object to denoise.

    Returns:
        Image: The denoised image object.
    """

    T = time.time()
    logger.info("DENOISE: Doing Denoise pass on %s...", image.name)

    # Preparing settings
    book = prepare_composite_settings(use_hdr=image.is_float)

    # Get window context and temp scene
    window_ctx = book.get("window_ctx")
    temp_scene = bpy.data.scenes.get(book['temp_scene_name'])

    # Create context override with temp scene
    if window_ctx:
        ctx_override = window_ctx.copy()
        ctx_override['scene'] = temp_scene
    else:
        ctx_override = {'scene': temp_scene}

    # Work within the temp scene context
    with bpy.context.temp_override(**ctx_override):
        scene = bpy.context.scene

        # Set up compositor
        tree = get_compositor_node_tree(scene)
        composite = get_compositor_output_node(tree)
        denoise = tree.nodes.new("CompositorNodeDenoise")
        if is_bl_newer_than(5):
            denoise.inputs.get("HDR").default_value = image.is_float
        else:
            denoise.use_hdr = image.is_float
        image_node = tree.nodes.new("CompositorNodeImage")
        image_node.image = image

        gamma = None
        if image.colorspace_settings.name != get_srgb_name() and not image.is_float:
            nodeid = "ShaderNodeGamma" if is_bl_newer_than(5) else "CompositorNodeGamma"
            gamma = tree.nodes.new(nodeid)
            gamma.inputs[1].default_value = 2.2

        rgb = image_node.outputs[0]
        if gamma:
            tree.links.new(rgb, gamma.inputs[0])
            rgb = gamma.outputs[0]
        tree.links.new(rgb, denoise.inputs["Image"])
        rgb = denoise.outputs[0]
        tree.links.new(rgb, composite.inputs[0])

        if image.source == "TILED":
            tilenums = [tile.number for tile in image.tiles]
        else:
            tilenums = [1001]

        # Save once before processing all tiles (Optimization: defer_save)
        if image.source == "TILED":
            save_udim(image)

        try:
            for tilenum in tilenums:

                # Swap tile to 1001 to access the data (defer saves for performance)
                if tilenum != 1001:
                    swap_tile(image, 1001, tilenum, defer_save=True)

                # Set render resolution
                scene.render.resolution_x = image.size[0]
                scene.render.resolution_y = image.size[1]

                # Render image (already in correct context)
                bpy.ops.render.render()

                # Copy pixels directly from render result (no temp file I/O)
                render_result = next(
                    img for img in bpy.data.images if img.type == "RENDER_RESULT"
                )
                copy_image_pixels(render_result, image)

                # Swap back the tile (defer saves for performance)
                if tilenum != 1001:
                    swap_tile(image, 1001, tilenum, defer_save=True)
        finally:
            # Ensure final save always happens
            if image.source == "TILED":
                save_udim(image)
                # Repack if image was originally packed
                if image.packed_file:
                    pack_udim(image)

    # Recover settings
    recover_composite_settings(book)

    logger.info(
        "DENOISE: %s denoise pass is done in %s seconds!",
        image.name,
        "{:0.2f}".format(time.time() - T),
    )
    return image


def dither_image(image, dither_intensity=1.0, alpha_aware=True):
    """Apply dithering to a float image for reducing banding artifacts.

    Args:
        image: Blender image object to dither.
        dither_intensity (float, optional): Intensity of dithering effect. Defaults to 1.0.
        alpha_aware (bool, optional): Apply dithering considering alpha channel. Defaults to True.

    Returns:
        Image: The dithered image object or None if image is not float.
    """
    if not image.is_float:
        logger.warning(
            "DITHER: Cannot dither image '%s' since it's not a float image",
            image.name,
        )
        return

    T = time.time()
    logger.info("DITHER: Doing dithering pass on %s...", image.name)

    # Preparing settings
    book = prepare_composite_settings(use_hdr=image.is_float)

    # Get window context and temp scene
    window_ctx = book.get("window_ctx")
    temp_scene = bpy.data.scenes.get(book['temp_scene_name'])

    # Create context override with temp scene
    if window_ctx:
        ctx_override = window_ctx.copy()
        ctx_override['scene'] = temp_scene
    else:
        ctx_override = {'scene': temp_scene}

    # Work within the temp scene context
    with bpy.context.temp_override(**ctx_override):
        scene = bpy.context.scene

        # Set render to byte image
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.image_settings.color_depth = "8"
        scene.render.dither_intensity = dither_intensity

        # Set up compositor
        tree = get_compositor_node_tree(scene)
        if not tree:
            # Compositor not enabled - enable it
            scene.use_nodes = True
            tree = get_compositor_node_tree(scene)

        if not tree:
            # Still no tree - cannot proceed with dithering
            logger.warning("Could not get compositor node tree for dithering")
            recover_composite_settings(book)
            return

        composite = get_compositor_output_node(tree)
        if not composite:
            logger.warning("Could not get compositor output node for dithering")
            recover_composite_settings(book)
            return

        image_node = tree.nodes.new("CompositorNodeImage")
        image_node.image = image

        if image.source == "TILED":
            tilenums = [tile.number for tile in image.tiles]
        else:
            tilenums = [1001]

        prefix_filename = "DITHER_RENDER___"
        temp_images = []
        temp_filepaths = []

        # Render dithered byte images
        for i, tilenum in enumerate(tilenums):

            # Swap tile to 1001 to access the data
            if tilenum != 1001:
                swap_tile(image, 1001, tilenum)

            # Get temporary filepath
            filepath = os.path.join(
                tempfile.gettempdir(), prefix_filename + str(tilenum) + ".png"
            )
            temp_filepaths.append(filepath)

            # Set render resolution
            scene.render.resolution_x = image.size[0]
            scene.render.resolution_y = image.size[1]

            # Connect image's rgb
            tree.links.new(image_node.outputs[0], composite.inputs[0])

            # Disable alpha is necesarry if image has alpha
            if alpha_aware:
                composite.use_alpha = False

            # Render image (already in correct context)
            bpy.ops.render.render()

            # Save the image
            render_result = next(
                img for img in bpy.data.images if img.type == "RENDER_RESULT"
            )
            render_result.save_render(filepath)
            temp_image = bpy.data.images.load(filepath)
            temp_images.append(temp_image)

            if alpha_aware:
                composite.use_alpha = True

                # Render alpha image!
                bpy.ops.render.render()

                # Save alpha image
                alpha_filepath = os.path.join(
                    tempfile.gettempdir(), prefix_filename + str(tilenum) + "_ALPHA.png"
                )
                render_result = next(
                    img for img in bpy.data.images if img.type == "RENDER_RESULT"
                )
                render_result.save_render(alpha_filepath)
                alpha_image = bpy.data.images.load(alpha_filepath)

                copy_image_channel_pixels(alpha_image, temp_image, 3, 3)

                # Remove alpha image
                remove_datablock(bpy.data.images, alpha_image)
                os.remove(alpha_filepath)

            # Swap back the tile
            if tilenum != 1001:
                swap_tile(image, 1001, tilenum)

    # Convert input image to byte (import needed function)
    from ...image_ops.image_ops_utils import toggle_image_bit_depth
    image = toggle_image_bit_depth(image, no_copy=True, force_srgb=True)

    # Copy images
    for i, tilenum in enumerate(tilenums):

        # Swap tile to 1001 to access the data
        if tilenum != 1001:
            swap_tile(image, 1001, tilenum)

        # Get temporary image
        temp_image = temp_images[i]
        filepath = temp_filepaths[i]

        # Copy image pixels
        copy_image_pixels(temp_image, image)

        # Remove temp image
        remove_datablock(bpy.data.images, temp_image)
        os.remove(filepath)

        # Swap back the tile
        if tilenum != 1001:
            swap_tile(image, 1001, tilenum)

    # Recover settings
    recover_composite_settings(book)

    logger.info(
        "DENOISE: %s dithering pass is done in %s seconds!",
        image.name,
        "{:0.2f}".format(time.time() - T),
    )
    return image
