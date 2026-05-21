# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Normal overlay baking functions - handles normal overlay (normal without bump) baking."""

from mixar.config.logging_config import get_logger

import bpy

logger = get_logger(__name__)

# Core imports
from ....core.io.utils.io_utils import create_link
from ....core.node.create_nodes import new_node
from ....core.node.node_utils import remove_node

# Utility imports
from ....utils.blender_commons import (
    get_all_image_users,
    get_noncolor_name,
    remove_datablock,
)
from ....utils.constants import TREE_END

# UDIM imports
from ...udim.udim_operators_helper import fill_tiles
from ...udim.udim_utils import initial_pack_udim

# Bake common imports
from .bake_common import (
    bake_object_op,
    is_baked_normal_without_bump_needed,
)


def bake_normal_overlay(
    tree,
    root_ch,
    img,
    tex,
    bsdf,
    output,
    emit,
    scene,
    use_udim,
    filepath,
    ori_normal_space,
):
    """Bake normal overlay (normal without bump).

    Parameters:
        tree: Node tree
        root_ch: Root channel
        img: Base image to copy from
        tex: Texture node for baking
        bsdf: BSDF node
        output: Output node
        emit: Emission node
        scene: Blender scene
        use_udim (bool): Whether using UDIM
        filepath (str): Filepath for the image
        ori_normal_space: Original normal space setting

    Returns:
        None
    """
    if not is_baked_normal_without_bump_needed(root_ch):
        # Remove baked_normal_overlay
        remove_node(tree, root_ch, "baked_normal_overlay")
        return

    baked_normal_overlay = tree.nodes.get(root_ch.baked_normal_overlay)
    if not baked_normal_overlay:
        baked_normal_overlay = new_node(
            tree,
            root_ch,
            "baked_normal_overlay",
            "ShaderNodeTexImage",
            "Baked " + root_ch.name + " Overlay Only",
        )
        if hasattr(baked_normal_overlay, "color_space"):
            baked_normal_overlay.color_space = "NONE"

    if baked_normal_overlay.image:
        norm_img_name = baked_normal_overlay.image.name
        filepath = baked_normal_overlay.image.filepath
        baked_normal_overlay.image.name = "____NORM_TEMP"
    else:
        norm_img_name = tree.name + " " + root_ch.name + " without Bump"

    # Create target image (copy inherits float buffer from source)
    norm_img = img.copy()
    norm_img.name = norm_img_name
    norm_img.colorspace_settings.name = get_noncolor_name()
    color = (0.5, 0.5, 1.0, 1.0)

    logger.info(
        "BAKE_NORMAL_OVERLAY: Created overlay image '%s', source is_float=%s, copy is_float=%s",
        norm_img.name, img.is_float, norm_img.is_float
    )

    if img.source == "TILED":
        fill_tiles(norm_img, color)
        initial_pack_udim(norm_img, color)
    else:
        norm_img.generated_color = color
        if filepath != "" and (
            (use_udim and ".<UDIM>." in filepath)
            or (not use_udim and ".<UDIM>." not in filepath)
        ):
            norm_img.filepath = filepath

    tex.image = norm_img

    # Bake setup (doing hacky reconnection here)
    end = tree.nodes.get(TREE_END)
    end_linear = tree.nodes.get(root_ch.end_linear)
    if end_linear:
        ori_soc = end.inputs[root_ch.name].links[0].from_socket
        soc = end_linear.inputs["Normal Overlay"].links[0].from_socket
        create_link(tree, soc, end.inputs[root_ch.name])

    # Preparing for normal baking
    if bsdf:
        scene.cycles.bake_type = "NORMAL"
        scene.render.bake.normal_space = "TANGENT"
        bsdf.id_data.links.new(bsdf.outputs[0], output.inputs[0])

    # Bake
    logger.info(
        "BAKE CHANNEL: Baking normal without bump image of %s channel...",
        root_ch.name,
    )
    bake_object_op(scene.cycles.bake_type)

    # Recover normal baking related
    if bsdf:
        scene.cycles.bake_type = "EMIT"
        scene.render.bake.normal_space = ori_normal_space
        emit.id_data.links.new(emit.outputs[0], output.inputs[0])

    # Recover connection
    if end_linear:
        create_link(tree, ori_soc, end.inputs[root_ch.name])

    # Set baked normal without bump image
    if baked_normal_overlay.image:
        temp = baked_normal_overlay.image
        img_users = get_all_image_users(baked_normal_overlay.image)
        for user in img_users:
            user.image = norm_img
        remove_datablock(bpy.data.images, temp)
    else:
        baked_normal_overlay.image = norm_img
