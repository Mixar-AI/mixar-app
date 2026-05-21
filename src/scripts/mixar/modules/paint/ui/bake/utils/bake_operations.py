# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Core baking operation functions"""

from mixar.config.logging_config import get_logger

import time

import bpy

from ....core.io.utils.io_utils import create_link
from ....core.layer.check_channels import check_all_channel_ios
from ....core.layer.check_layers import (
    any_layers_using_disp,
    any_layers_using_vdisp,
    is_overlay_normal_empty,
)
from ....core.layer.layer_utils import get_uv_layers
from ....core.node.get_nodes import get_material_output
from ....core.node.node_utils import get_active_mpaint_node
from ....utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_noncolor_name,
    remove_datablock,
    simple_remove_node,
)
from ....utils.constants import io_suffix
from .bake_settings_manager import (
    prepare_bake_settings,
    recover_bake_settings,
    remember_before_bake,
)

logger = get_logger(__name__)


def bake_object_op(bake_type="EMIT"):
    """Execute bake operation with fallback to CPU if GPU fails.

    Args:
        bake_type (str, optional): Type of bake operation. Defaults to "EMIT".
    """
    try:
        if bake_type != "EMIT":
            bpy.ops.object.bake(type=bake_type)
        else:
            bpy.ops.object.bake()
    except Exception as e:
        scene = bpy.context.scene
        if scene.cycles.device == "GPU":
            logger.warning("GPU baking failed! Trying to use CPU...")
            scene.cycles.device = "CPU"

            if bake_type != "EMIT":
                bpy.ops.object.bake(type=bake_type)
            else:
                bpy.ops.object.bake()
        else:
            logger.error("Baking exception: %s", e)


def is_baked_normal_without_bump_needed(root_ch):
    """Check if baked normal without bump is needed for the channel.

    Args:
        root_ch: Root channel property group.

    Returns:
        bool: True if baked normal without bump is needed, False otherwise.
    """
    return (
        not is_overlay_normal_empty(root_ch)
        and (any_layers_using_disp(root_ch) or any_layers_using_vdisp(root_ch))
    ) or (
        root_ch.enable_subdiv_setup
        and (any_layers_using_disp(root_ch) or any_layers_using_vdisp(root_ch))
    )


def get_bake_max_height(root_ch, mat=None, node=None, tex=None, emit=None):
    """Bake and get the maximum height value for a channel.

    Args:
        root_ch: Root channel property group.
        mat: Blender material object, defaults to None.
        node: MPaint node, defaults to None.
        tex: Texture node, defaults to None.
        emit: Emission node, defaults to None.

    Returns:
        float: Maximum height value from baked data.
    """

    T = time.time()
    logger.info("BAKE MAX HEIGHT: Doing Max Height baking on %s...", root_ch.name)

    tree = root_ch.id_data
    mp = tree.mp
    scene = bpy.context.scene
    if not mat:
        mat = get_active_material()
    if not node:
        node = get_active_mpaint_node()

    # Do setup first before baking
    book = {}
    ori_margin = scene.render.bake.margin
    high_margin = 1000
    ori_matout_inp = None
    if not tex and not emit:
        obj = get_active_object()
        uv_layers = get_uv_layers(obj)
        if len(uv_layers) == 0:
            return
        uv_map = uv_layers[0].name
        mat_out = get_material_output(mat)
        if not mat_out:
            return

        book = remember_before_bake()
        prepare_bake_settings(
            book,
            [obj],
            mp,
            samples=1,
            margin=high_margin,
            uv_map=uv_map,
            bake_device="CPU",
            margin_type="EXTEND",
        )

        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        emit = mat.node_tree.nodes.new("ShaderNodeEmission")

        # Connect emit to output material
        if len(mat_out.inputs[0].links) > 0:
            ori_matout_inp = mat_out.inputs[0].links[0].from_socket
        mat.node_tree.links.new(emit.outputs[0], mat_out.inputs[0])

        mat.node_tree.nodes.active = tex

    else:
        # Use high margin to make sure all pixels are covered
        scene.render.bake.margin = high_margin

    # Check for height socket
    forced_height_ios = False
    if "Height" not in node.outputs:
        check_all_channel_ios(mp, reconnect=True, force_height_io=True)
        forced_height_ios = True

    # Create target image
    img = bpy.data.images.new(
        name="____MAXHEIGHT_TEMP",
        width=100,
        height=100,
        alpha=False,
        tiled=False,
        float_buffer=True,
    )

    img.colorspace_settings.name = get_noncolor_name()
    tex.image = img

    # Connect max height output to emit node
    create_link(
        mat.node_tree,
        node.outputs[root_ch.name + io_suffix["MAX_HEIGHT"]],
        emit.inputs[0],
    )

    # Bake
    logger.info("BAKE MAX HEIGHT: Baking max height of %s channel...", root_ch.name)
    bake_object_op()

    # Set baked max height image
    max_height_value = img.pixels[0]

    # Remove max height image
    remove_datablock(bpy.data.images, img, user=tex, user_prop="image")

    if len(book) > 0:
        # Reconnect original output connections
        if ori_matout_inp:
            mat.node_tree.links.new(ori_matout_inp, mat_out.inputs[0])

        # Delete temporary nodes
        simple_remove_node(mat.node_tree, tex)
        simple_remove_node(mat.node_tree, emit)

        # Recover settings
        recover_bake_settings(book, mp)
    else:
        # Recover margin
        scene.render.bake.margin = ori_margin

    logger.info(
        "BAKE MAX HEIGHT: Max height baking is done in %s seconds!",
        "{:0.2f}".format(time.time() - T),
    )
    return max_height_value
