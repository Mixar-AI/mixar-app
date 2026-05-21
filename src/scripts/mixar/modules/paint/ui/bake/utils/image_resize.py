# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image resize operations using baking.

This module contains functions for resizing images by baking them to new
resolutions, with support for alpha channels, UDIM tiles, and image atlases.
"""

from mixar.config.logging_config import get_logger

import time

import bpy

from ....core.element.update_image import (
    copy_image_channel_pixels,
    copy_image_pixels,
    replace_image,
)
from ....core.layer.layer_utils import get_uv_layers
from ....core.lib.lib import STRAIGHT_OVER
from ....core.node.get_nodes import get_active_mat_output_node
from ....core.node.node_utils import get_node_tree_lib
from ....utils.blender_commons import (
    get_noncolor_name,
    remove_datablock,
    remove_mesh_obj,
)
from ...udim.udim_utils import fill_tile, swap_tile
from .bake_settings_manager import (
    prepare_bake_settings,
    recover_bake_settings,
    remember_before_bake,
)
from .bake_temp_materials import create_plane_on_object_mode

logger = get_logger(__name__)


def resize_image(
    image,
    width,
    height,
    colorspace="Non-Color",
    samples=1,
    margin=0,
    segment=None,
    alpha_aware=True,
    mp=None,
    bake_device="CPU",
    specific_tile=0,
):
    """Resize an image by baking it to a new resolution.

    Args:
        image: Blender image object to resize.
        width (int): Target width in pixels.
        height (int): Target height in pixels.
        colorspace (str, optional): Color space for the image. Defaults to "Non-Color".
        samples (int, optional): Number of samples for baking. Defaults to 1.
        margin (int, optional): Bake margin in pixels. Defaults to 0.
        segment: Image atlas segment, defaults to None.
        alpha_aware (bool, optional): Preserve alpha channel. Defaults to True.
        mp: MPaint node tree property group, defaults to None.
        bake_device (str, optional): Device to use for baking. Defaults to "CPU".
        specific_tile (int, optional): Specific UDIM tile number to resize. Defaults to 0.
    """

    T = time.time()
    image_name = image.name
    logger.info("RESIZE IMAGE: Doing resize image pass on %s...", image_name)

    if image.source != "TILED":
        if segment:
            ori_width = segment.width
            ori_height = segment.height
        else:
            ori_width = image.size[0]
            ori_height = image.size[1]

        if ori_width == width and ori_height == height:
            return

    book = remember_before_bake()

    if image.source == "TILED":
        if specific_tile < 1001:
            tilenums = [tile.number for tile in image.tiles]
        else:
            tilenums = [specific_tile]
    else:
        tilenums = [1001]

    # Set active collection to be root collection

    ori_layer_collection = bpy.context.view_layer.active_layer_collection
    bpy.context.view_layer.active_layer_collection = (
        bpy.context.view_layer.layer_collection
    )

    # Create new plane
    bpy.ops.object.mode_set(mode="OBJECT")
    plane_obj = create_plane_on_object_mode()

    prepare_bake_settings(
        book, [plane_obj], samples=samples, margin=margin, bake_device=bake_device
    )

    mat = bpy.data.materials.new("__TEMP__")
    mat.use_nodes = True
    plane_obj.active_material = mat

    output = get_active_mat_output_node(mat.node_tree)
    emi = mat.node_tree.nodes.new("ShaderNodeEmission")
    uv_map = mat.node_tree.nodes.new("ShaderNodeUVMap")
    # uv_map.uv_map = 'UVMap' # Will use active UV instead since every language has different default UV name
    target_tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    source_tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    source_tex.image = image

    straight_over = mat.node_tree.nodes.new("ShaderNodeGroup")
    straight_over.node_tree = get_node_tree_lib(STRAIGHT_OVER)
    straight_over.inputs[1].default_value = 0.0

    # Connect nodes
    mat.node_tree.links.new(uv_map.outputs[0], source_tex.inputs[0])
    mat.node_tree.links.new(emi.outputs[0], output.inputs[0])
    mat.node_tree.nodes.active = target_tex

    new_segment = None

    for tilenum in tilenums:

        # Swap tile to 1001 to access the data
        if tilenum != 1001:
            swap_tile(image, 1001, tilenum)

        if segment:
            from ...image_atlas.image_atlas_utils import get_set_image_atlas_segment
            new_segment = get_set_image_atlas_segment(
                width, height, image.yia.color, image.is_float, mp=mp
            )
            scaled_img = new_segment.id_data

            ori_start_x = segment.width * segment.tile_x
            ori_start_y = segment.height * segment.tile_y

            start_x = width * new_segment.tile_x
            start_y = height * new_segment.tile_y

            # If using image atlas, transform uv
            uv_layers = get_uv_layers(plane_obj)

            # Transform current uv using previous segment
            for i, d in enumerate(plane_obj.data.uv_layers.active.data):
                if i == 0:  # Top right
                    d.uv.x = (ori_start_x + segment.width) / image.size[0]
                    d.uv.y = (ori_start_y + segment.height) / image.size[1]
                elif i == 1:  # Top left
                    d.uv.x = ori_start_x / image.size[0]
                    d.uv.y = (ori_start_y + segment.height) / image.size[1]
                elif i == 2:  # Bottom left
                    d.uv.x = ori_start_x / image.size[0]
                    d.uv.y = ori_start_y / image.size[1]
                elif i == 3:  # Bottom right
                    d.uv.x = (ori_start_x + segment.width) / image.size[0]
                    d.uv.y = ori_start_y / image.size[1]

            # Create new uv and transform it using new segment
            temp_uv_layer = uv_layers.new(name="__TEMP")
            uv_layers.active = temp_uv_layer
            for i, d in enumerate(plane_obj.data.uv_layers.active.data):
                if i == 0:  # Top right
                    d.uv.x = (start_x + width) / scaled_img.size[0]
                    d.uv.y = (start_y + height) / scaled_img.size[1]
                elif i == 1:  # Top left
                    d.uv.x = start_x / scaled_img.size[0]
                    d.uv.y = (start_y + height) / scaled_img.size[1]
                elif i == 2:  # Bottom left
                    d.uv.x = start_x / scaled_img.size[0]
                    d.uv.y = start_y / scaled_img.size[1]
                elif i == 3:  # Bottom right
                    d.uv.x = (start_x + width) / scaled_img.size[0]
                    d.uv.y = start_y / scaled_img.size[1]

        else:
            scaled_img = bpy.data.images.new(
                name="__TEMP__",
                width=width,
                height=height,
                alpha=True,
                float_buffer=image.is_float,
            )
            scaled_img.colorspace_settings.name = colorspace
            if image.filepath != "" and not image.packed_file:
                scaled_img.filepath = image.filepath

        # Reconnect bake setup nodes
        mat.node_tree.links.new(source_tex.outputs[0], straight_over.inputs[2])
        mat.node_tree.links.new(source_tex.outputs[1], straight_over.inputs[3])
        mat.node_tree.links.new(straight_over.outputs[0], emi.inputs[0])

        # Set image target
        target_tex.image = scaled_img

        # Bake
        logger.info("RESIZE IMAGE: Baking resized image on %s...", image_name)
        from .bake_operations import bake_object_op
        bake_object_op()

        if alpha_aware:

            # Create alpha image as bake target
            alpha_img = bpy.data.images.new(
                name="__TEMP_ALPHA__",
                width=width,
                height=height,
                alpha=True,
                float_buffer=image.is_float,
            )
            alpha_img.colorspace_settings.name = get_noncolor_name()

            # Retransform back uv
            if segment:
                for i, d in enumerate(plane_obj.data.uv_layers.active.data):
                    if i == 0:  # Top right
                        d.uv.x = 1.0
                        d.uv.y = 1.0
                    elif i == 1:  # Top left
                        d.uv.x = 0.0
                        d.uv.y = 1.0
                    elif i == 2:  # Bottom left
                        d.uv.x = 0.0
                        d.uv.y = 0.0
                    elif i == 3:  # Bottom right
                        d.uv.x = 1.0
                        d.uv.y = 0.0

            # Setup texture
            target_tex.image = alpha_img
            mat.node_tree.links.new(source_tex.outputs[1], emi.inputs[0])

            # Bake again!
            logger.info("RESIZE IMAGE: Baking resized alpha on %s...", image_name)
            from .bake_operations import bake_object_op
            bake_object_op()

            if new_segment:
                copy_image_channel_pixels(alpha_img, scaled_img, 0, 3, new_segment)
            else:
                copy_image_channel_pixels(alpha_img, scaled_img, 0, 3, segment)

            # Remove alpha image
            remove_datablock(bpy.data.images, alpha_img)

        if image.source == "TILED":
            # Resize tile first
            fill_tile(image, 1001, image.generated_color, width, height)

            # Copy resized image to tile
            copy_image_pixels(scaled_img, image)

            remove_datablock(bpy.data.images, scaled_img)
        else:
            if not new_segment:
                # Replace original image to scaled image
                replace_image(image, scaled_img)
            image = scaled_img

        # Swap back the tile
        if tilenum != 1001:
            swap_tile(image, 1001, tilenum)

    # Remove temp data
    if straight_over.node_tree.users == 1:
        remove_datablock(
            bpy.data.node_groups,
            straight_over.node_tree,
            user=straight_over,
            user_prop="node_tree",
        )
    remove_datablock(bpy.data.materials, mat)
    remove_mesh_obj(plane_obj)

    # Recover settings
    recover_bake_settings(book)

    # Recover original active layer collection
    bpy.context.view_layer.active_layer_collection = ori_layer_collection

    logger.info(
        "RESIZE IMAGE: %s Resize image is done in %s seconds!",
        image_name,
        "{:0.2f}".format(time.time() - T),
    )
