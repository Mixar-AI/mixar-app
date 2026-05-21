# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Displacement baking helper functions - handles vector displacement and displacement baking."""

from mixar.config.logging_config import get_logger

import bpy

logger = get_logger(__name__)

# Core imports
from ....core.io.utils.io_utils import create_link
from ....core.layer.check_layers import any_layers_using_disp, any_layers_using_vdisp
from ....core.lib.lib import SPREAD_NORMALIZED_HEIGHT
from ....core.node.create_nodes import check_new_node, new_node
from ....core.node.node_utils import get_node_tree_lib, remove_node

# Utility imports
from ....utils.blender_commons import (
    get_all_image_users,
    get_noncolor_name,
    remove_datablock,
    simple_remove_node,
)
from ....utils.common import set_entity_prop_value
from ....utils.constants import io_suffix

# UDIM imports
from ...udim.udim_operators_helper import fill_tiles
from ...udim.udim_utils import initial_pack_udim

# Bake common imports
from .bake_common import (
    bake_object_op,
    get_bake_max_height,
)


def bake_vector_displacement(tree, root_ch, img, tex, node, mat, emit, use_udim, filepath):
    """Bake vector displacement.

    Parameters:
        tree: Node tree
        root_ch: Root channel
        img: Base image to copy from
        tex: Texture node for baking
        node: MPaint node
        mat: Material
        emit: Emission node
        use_udim (bool): Whether using UDIM
        filepath (str): Filepath for the image

    Returns:
        None
    """
    if not any_layers_using_vdisp(root_ch):
        # Remove baked_vdisp
        remove_node(tree, root_ch, "baked_vdisp")
        return

    baked_vdisp = tree.nodes.get(root_ch.baked_vdisp)
    if not baked_vdisp:
        baked_vdisp = new_node(
            tree,
            root_ch,
            "baked_vdisp",
            "ShaderNodeTexImage",
            "Baked " + root_ch.name + " Vector Displacement",
        )
        if hasattr(baked_vdisp, "color_space"):
            baked_vdisp.color_space = "NONE"

    if baked_vdisp.image:
        vdisp_img_name = baked_vdisp.image.name
        filepath = baked_vdisp.image.filepath
        baked_vdisp.image.name = "____VDISP_TEMP"
    else:
        vdisp_img_name = tree.name + " " + root_ch.name + " Vector Displacement"

    # Set interpolation to cubic
    baked_vdisp.interpolation = "Cubic"

    color = (0.0, 0.0, 0.0, 1.0)

    # Create new image with float buffer (vector displacement always needs float)
    # (img.copy() doesn't allow changing float buffer depth)
    if img.source == "TILED":
        vdisp_img = bpy.data.images.new(
            name=vdisp_img_name,
            width=img.size[0],
            height=img.size[1],
            alpha=True,
            tiled=True,
            float_buffer=True,
        )
        # Copy tile structure from source
        for tile in img.tiles:
            if tile.number != 1001:
                vdisp_img.tiles.new(tile_number=tile.number)
        fill_tiles(vdisp_img, color)
        initial_pack_udim(vdisp_img, color)
    else:
        vdisp_img = bpy.data.images.new(
            name=vdisp_img_name,
            width=img.size[0],
            height=img.size[1],
            alpha=True,
            float_buffer=True,
        )
        vdisp_img.generated_color = color
        if filepath != "" and (
            (use_udim and ".<UDIM>." in filepath)
            or (not use_udim and ".<UDIM>." not in filepath)
        ):
            vdisp_img.filepath = filepath

    vdisp_img.colorspace_settings.name = get_noncolor_name()

    logger.info(
        "BAKE_VDISP: Created vector displacement image '%s', is_float=%s",
        vdisp_img.name, vdisp_img.is_float
    )

    tex.image = vdisp_img

    # Bake setup
    create_link(
        mat.node_tree,
        node.outputs[root_ch.name + io_suffix["VDISP"]],
        emit.inputs[0],
    )

    # Bake
    logger.info(
        "BAKE CHANNEL: Baking vector displacement image of %s channel...",
        root_ch.name,
    )
    bake_object_op()

    # Set baked vector displacement image
    if baked_vdisp.image:
        temp = baked_vdisp.image
        img_users = get_all_image_users(baked_vdisp.image)
        for user in img_users:
            user.image = vdisp_img
        remove_datablock(bpy.data.images, temp)
    else:
        baked_vdisp.image = vdisp_img


def bake_displacement(
    tree,
    root_ch,
    img,
    tex,
    node,
    mat,
    emit,
    use_udim,
    filepath,
    use_float_for_displacement,
):
    """Bake displacement image.

    Parameters:
        tree: Node tree
        root_ch: Root channel
        img: Base image to copy from
        tex: Texture node for baking
        node: MPaint node
        mat: Material
        emit: Emission node
        use_udim (bool): Whether using UDIM
        filepath (str): Filepath for the image
        use_float_for_displacement (bool): Use float for displacement

    Returns:
        Image or None: Displacement image if created
    """
    if not any_layers_using_disp(root_ch):
        # Remove baked_disp
        remove_node(tree, root_ch, "baked_disp")
        remove_node(tree, root_ch, "end_max_height")
        return None

    # Max Height
    max_height_value = get_bake_max_height(root_ch, mat, node, tex, emit)
    end_max_height = check_new_node(
        tree, root_ch, "end_max_height", "ShaderNodeValue", "Max Height"
    )
    end_max_height.outputs[0].default_value = max_height_value

    # Displacement
    baked_disp = tree.nodes.get(root_ch.baked_disp)
    if not baked_disp:
        baked_disp = new_node(
            tree,
            root_ch,
            "baked_disp",
            "ShaderNodeTexImage",
            "Baked " + root_ch.name + " Displacement",
        )
        if hasattr(baked_disp, "color_space"):
            baked_disp.color_space = "NONE"

    if baked_disp.image:
        disp_img_name = baked_disp.image.name
        filepath = baked_disp.image.filepath
        baked_disp.image.name = "____DISP_TEMP"
    else:
        disp_img_name = tree.name + " Displacement"

    # Set interpolation to cubic
    baked_disp.interpolation = "Cubic"

    color = (0.5, 0.5, 0.5, 1.0)

    # Create new image with correct float buffer setting
    # (img.copy() doesn't allow changing float buffer depth)
    if img.source == "TILED":
        disp_img = bpy.data.images.new(
            name=disp_img_name,
            width=img.size[0],
            height=img.size[1],
            alpha=True,
            tiled=True,
            float_buffer=use_float_for_displacement,
        )
        # Copy tile structure from source
        for tile in img.tiles:
            if tile.number != 1001:
                disp_img.tiles.new(tile_number=tile.number)
        fill_tiles(disp_img, color)
        initial_pack_udim(disp_img, color)
    else:
        disp_img = bpy.data.images.new(
            name=disp_img_name,
            width=img.size[0],
            height=img.size[1],
            alpha=True,
            float_buffer=use_float_for_displacement,
        )
        disp_img.generated_color = color
        if filepath != "" and (
            (use_udim and ".<UDIM>." in filepath)
            or (not use_udim and ".<UDIM>." not in filepath)
        ):
            disp_img.filepath = filepath

    disp_img.colorspace_settings.name = get_noncolor_name()

    logger.info(
        "BAKE_DISPLACEMENT: Created displacement image '%s', use_float_for_displacement=%s, is_float=%s",
        disp_img.name, use_float_for_displacement, disp_img.is_float
    )

    return disp_img, baked_disp


def bake_displacement_image(
    disp_img,
    baked_disp,
    tree,
    root_ch,
    tex,
    node,
    mat,
    emit,
    target_layer=None,
    ch=None,
):
    """Perform the actual displacement bake operation.

    Parameters:
        disp_img: Displacement image
        baked_disp: Baked displacement node
        tree: Node tree
        root_ch: Root channel
        tex: Texture node
        node: MPaint node
        mat: Material
        emit: Emission node
        target_layer: Optional target layer
        ch: Optional channel

    Returns:
        None
    """
    # Bake setup
    spread_height = None
    if target_layer and target_layer.parent_idx == -1:
        spread_height = mat.node_tree.nodes.new("ShaderNodeGroup")
        spread_height.node_tree = get_node_tree_lib(SPREAD_NORMALIZED_HEIGHT)

        create_link(
            mat.node_tree,
            node.outputs[root_ch.name + io_suffix["HEIGHT"]],
            spread_height.inputs[0],
        )
        create_link(
            mat.node_tree,
            node.outputs[root_ch.name + io_suffix["ALPHA"]],
            spread_height.inputs[1],
        )
        create_link(mat.node_tree, spread_height.outputs[0], emit.inputs[0])
    else:
        create_link(
            mat.node_tree,
            node.outputs[root_ch.name + io_suffix["HEIGHT"]],
            emit.inputs[0],
        )

    tex.image = disp_img

    # Bake
    logger.info(
        "BAKE CHANNEL: Baking displacement image of %s channel...",
        root_ch.name,
    )
    bake_object_op()

    if target_layer:
        # Get max height value
        max_height_value = get_bake_max_height(root_ch, mat, node, tex, emit)
        if ch:
            set_entity_prop_value(ch, "bump_distance", max_height_value)
    else:
        # Set baked displacement image
        if baked_disp.image:
            temp = baked_disp.image
            img_users = get_all_image_users(baked_disp.image)
            for user in img_users:
                user.image = disp_img
            remove_datablock(bpy.data.images, temp)
        else:
            baked_disp.image = disp_img

    if spread_height:
        simple_remove_node(mat.node_tree, spread_height)
