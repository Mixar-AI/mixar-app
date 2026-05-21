# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bake-based image processing effects.

This module contains image processing functions that use Blender's baking
system for effects like noise blur and FXAA anti-aliasing.
"""

from mixar.config.logging_config import get_logger

import time

import bpy
import numpy

from ....core.element.update_image import copy_image_channel_pixels
from ....core.lib.lib import BLUR_VECTOR, FXAA, STRAIGHT_OVER
from ....core.node.get_nodes import get_active_mat_output_node
from ....core.node.node_utils import get_node_tree_lib
from ....utils.blender_commons import (
    duplicate_image,
    remove_datablock,
    remove_mesh_obj,
)
from ...udim.udim_utils import swap_tile
from ...udim.udim_utils_io import pack_udim, save_udim
from .bake_settings_manager import (
    prepare_bake_settings,
    recover_bake_settings,
    remember_before_bake,
)
from .bake_temp_materials import create_plane_on_object_mode

logger = get_logger(__name__)


def noise_blur_image(
    image, alpha_aware=True, factor=1.0, samples=512, bake_device="CPU"
):
    """Apply noise-based blur effect to an image using baking.

    Args:
        image: Blender image object to blur.
        alpha_aware (bool, optional): Apply blur considering alpha channel. Defaults to True.
        factor (float, optional): Blur factor/intensity. Defaults to 1.0.
        samples (int, optional): Number of samples for baking. Defaults to 512.
        bake_device (str, optional): Device to use for baking. Defaults to "CPU".

    Returns:
        Image: The blurred image object.
    """
    T = time.time()
    logger.info("BLUR: Doing Blur pass on %s...", image.name)
    book = remember_before_bake()

    width = image.size[0]
    height = image.size[1]

    # Set active collection to be root collection
    ori_layer_collection = bpy.context.view_layer.active_layer_collection
    bpy.context.view_layer.active_layer_collection = (
        bpy.context.view_layer.layer_collection
    )

    # Create new plane
    bpy.ops.object.mode_set(mode="OBJECT")
    plane_obj = create_plane_on_object_mode()

    prepare_bake_settings(
        book, [plane_obj], samples=samples, margin=0, bake_device=bake_device
    )

    # Create temporary material
    mat = bpy.data.materials.new("__TEMP__")
    mat.use_nodes = True
    plane_obj.active_material = mat

    # Create nodes
    output = get_active_mat_output_node(mat.node_tree)
    emi = mat.node_tree.nodes.new("ShaderNodeEmission")

    uv_map = mat.node_tree.nodes.new("ShaderNodeUVMap")
    # uv_map.uv_map = 'UVMap' # Will use active UV instead since every language has different default UV name

    blur = mat.node_tree.nodes.new("ShaderNodeGroup")
    blur.node_tree = get_node_tree_lib(BLUR_VECTOR)
    blur.inputs[0].default_value = factor

    source_tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    target_tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    target_tex.image = image

    # Connect nodes

    mat.node_tree.links.new(uv_map.outputs[0], blur.inputs[1])
    mat.node_tree.links.new(blur.outputs[0], source_tex.inputs[0])

    mat.node_tree.links.new(emi.outputs[0], output.inputs[0])
    mat.node_tree.nodes.active = target_tex

    if image.source == "TILED":
        tilenums = [tile.number for tile in image.tiles]
    else:
        tilenums = [1001]

    for tilenum in tilenums:

        # Swap tile to 1001 to access the data
        if tilenum != 1001:
            swap_tile(image, 1001, tilenum)

        width = image.size[0]
        height = image.size[1]

        # Copy image
        image_copy = duplicate_image(image)

        # Set source image
        source_tex.image = image_copy

        # Connect nodes again
        mat.node_tree.links.new(source_tex.outputs[0], emi.inputs[0])
        mat.node_tree.links.new(emi.outputs[0], output.inputs[0])

        logger.info("BLUR: Baking blur on %s...", image.name)
        from .bake_operations import bake_object_op
        bake_object_op()

        # Run alpha pass
        if alpha_aware:
            logger.info("BLUR: Running alpha pass to blur result of %s...", image.name)

            # TODO: Bake blur on alpha channel
            pass

            # TODO: Bake straight over on blurred rgb
            pass

            # TODO: Copy result to main image
            # copy_image_channel_pixels(image_copy, image, 3, 3)

        # Swap back the tile
        if tilenum != 1001:
            swap_tile(image, 1001, tilenum)

        # Remove temp images
        remove_datablock(
            bpy.data.images, image_copy, user=source_tex, user_prop="image"
        )

    # Remove temp datas
    logger.info("BLUR: Removing temporary data of blur pass")
    if alpha_aware:
        if straight_over.node_tree.users == 1:
            remove_datablock(
                bpy.data.node_groups,
                straight_over.node_tree,
                user=straight_over,
                user_prop="node_tree",
            )

    if blur.node_tree.users == 1:
        remove_datablock(
            bpy.data.node_groups, blur.node_tree, user=blur, user_prop="node_tree"
        )

    remove_datablock(bpy.data.materials, mat)
    remove_mesh_obj(plane_obj)

    # Recover settings
    recover_bake_settings(book)

    # Recover original active layer collection
    bpy.context.view_layer.active_layer_collection = ori_layer_collection

    logger.info(
        "BLUR: %s blur pass is done in %s seconds!",
        image.name,
        "{:0.2f}".format(time.time() - T),
    )

    return image


def fxaa_image(image, alpha_aware=True, bake_device="CPU", first_tile_only=False):
    """Apply FXAA (Fast Approximate Anti-Aliasing) to an image.

    Args:
        image: Blender image object to process.
        alpha_aware (bool, optional): Preserve original alpha channel. Defaults to True.
        bake_device (str, optional): Device to use for baking. Defaults to "CPU".
        first_tile_only (bool, optional): Only process first tile for UDIM images. Defaults to False.

    Returns:
        Image: The processed image object.
    """
    T = time.time()
    logger.info("FXAA: Doing FXAA pass on %s...", image.name)
    book = remember_before_bake()

    # Set active collection to be root collection
    ori_layer_collection = bpy.context.view_layer.active_layer_collection
    bpy.context.view_layer.active_layer_collection = (
        bpy.context.view_layer.layer_collection
    )

    # Create new plane
    bpy.ops.object.mode_set(mode="OBJECT")
    plane_obj = create_plane_on_object_mode()

    prepare_bake_settings(
        book, [plane_obj], samples=1, margin=0, bake_device=bake_device
    )

    # Create temporary material
    mat = bpy.data.materials.new("__TEMP__")
    mat.use_nodes = True
    plane_obj.active_material = mat

    # Create nodes
    output = get_active_mat_output_node(mat.node_tree)
    emi = mat.node_tree.nodes.new("ShaderNodeEmission")

    target_tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    target_tex.image = image
    fxaa = mat.node_tree.nodes.new("ShaderNodeGroup")
    fxaa.node_tree = get_node_tree_lib(FXAA)

    # Connect nodes
    mat.node_tree.links.new(emi.outputs[0], output.inputs[0])
    mat.node_tree.nodes.active = target_tex

    if image.source == "TILED" and not first_tile_only:
        tilenums = [tile.number for tile in image.tiles]
    else:
        tilenums = [1001]

    # Save once before processing all tiles (Optimization: defer_save)
    if image.source == "TILED" and not first_tile_only:
        save_udim(image)

    try:
        for tilenum in tilenums:

            # Swap tile to 1001 to access the data (defer saves for performance)
            if tilenum != 1001:
                swap_tile(image, 1001, tilenum, defer_save=True)

            width = image.size[0]
            height = image.size[1]

            # Copy image using numpy arrays (50-100x faster than list conversion)
            pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
            image.pixels.foreach_get(pixels)
            image_ori = None
            image_copy = image.copy()
            image_copy.pixels.foreach_set(pixels)

            # Straight over won't work if using fxaa nodes, need another bake pass
            if alpha_aware:
                image_ori = image.copy()
                image_ori.pixels.foreach_set(pixels)

                uv_map = mat.node_tree.nodes.new("ShaderNodeUVMap")
                source_tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
                source_tex.image = image_copy

                straight_over = mat.node_tree.nodes.new("ShaderNodeGroup")
                straight_over.node_tree = get_node_tree_lib(STRAIGHT_OVER)
                straight_over.inputs[1].default_value = 0.0

                mat.node_tree.links.new(uv_map.outputs[0], source_tex.inputs[0])
                mat.node_tree.links.new(source_tex.outputs[0], straight_over.inputs[2])
                mat.node_tree.links.new(source_tex.outputs[1], straight_over.inputs[3])
                mat.node_tree.links.new(straight_over.outputs[0], emi.inputs[0])

                # Bake
                logger.info("FXAA: Baking straight over on %s...", image.name)
                from .bake_operations import bake_object_op
                bake_object_op()

                pixels_1 = numpy.empty(width * height * 4, dtype=numpy.float32)
                image.pixels.foreach_get(pixels_1)
                image_copy.pixels.foreach_set(pixels_1)

            # Fill fxaa nodes
            res_x = fxaa.node_tree.nodes.get("res_x")
            res_y = fxaa.node_tree.nodes.get("res_y")
            fxaa_uv_map = fxaa.node_tree.nodes.get("uv_map")
            tex_node = fxaa.node_tree.nodes.get("tex")
            tex = tex_node.node_tree.nodes.get("tex")

            res_x.outputs[0].default_value = width
            res_y.outputs[0].default_value = height
            tex.image = image_copy

            # Connect nodes again
            mat.node_tree.links.new(fxaa.outputs[0], emi.inputs[0])
            mat.node_tree.links.new(emi.outputs[0], output.inputs[0])

            logger.info("FXAA: Baking FXAA on %s...", image.name)
            from .bake_operations import bake_object_op
            bake_object_op()

            # Copy original alpha to baked image
            if alpha_aware:
                logger.info("FXAA: Copying original alpha to FXAA result of %s...", image.name)
                copy_image_channel_pixels(image_ori, image, 3, 3)

            # Swap back the tile (defer saves for performance)
            if tilenum != 1001:
                swap_tile(image, 1001, tilenum, defer_save=True)

            # Remove temp images
            remove_datablock(bpy.data.images, image_copy, user=tex, user_prop="image")
            if image_ori:
                remove_datablock(bpy.data.images, image_ori)
    finally:
        # Ensure final save always happens
        if image.source == "TILED" and not first_tile_only:
            save_udim(image)
            # Repack if image was originally packed
            if image.packed_file:
                pack_udim(image)

    # Remove temp datas
    logger.info("FXAA: Removing temporary data of FXAA pass")
    if alpha_aware:
        if straight_over.node_tree.users == 1:
            remove_datablock(
                bpy.data.node_groups,
                straight_over.node_tree,
                user=straight_over,
                user_prop="node_tree",
            )

    if fxaa.node_tree.users == 1:
        remove_datablock(
            bpy.data.node_groups,
            tex_node.node_tree,
            user=tex_node,
            user_prop="node_tree",
        )
        remove_datablock(
            bpy.data.node_groups, fxaa.node_tree, user=fxaa, user_prop="node_tree"
        )

    remove_datablock(bpy.data.materials, mat)
    remove_mesh_obj(plane_obj)

    # Recover settings
    recover_bake_settings(book)

    # Recover original active layer collection
    bpy.context.view_layer.active_layer_collection = ori_layer_collection

    logger.info(
        "FXAA: %s FXAA pass is done in %s seconds!",
        image.name,
        "{:0.2f}".format(time.time() - T),
    )

    return image
