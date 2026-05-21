# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Baked channel processing helpers for mp_connections.
"""

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.constants import (
    TREE_END,
    ZERO_VALUE,
    io_suffix,
)
from ...node.node_utils import get_essential_node
from ..utils.io_utils import break_input_link, create_link


def process_baked_channel(tree, mp, ch, nodes, rgb, alpha, baked_uv_map, channel_values, channel_nodes):
    """
    Process baked channel connections.

    Parameters:
        tree: The node tree.
        mp: The MPaint data from the tree.
        ch: The current channel.
        nodes: The nodes in the tree.
        rgb: Current RGB value.
        alpha: Current alpha value.
        baked_uv_map: Baked UV map output.
        channel_values: Current channel values.
        channel_nodes: Channel-related nodes.

    Returns:
        tuple: (rgb, alpha, height, max_height, vdisp)
    """
    height = channel_values.get("height")
    max_height = channel_values.get("max_height")
    vdisp = channel_values.get("vdisp")
    end_normal_engine_filter = channel_nodes.get("end_normal_engine_filter")
    end_max_height = channel_nodes.get("end_max_height")

    if not (
        mp.use_baked
        and not ch.no_layer_using
        and not ch.disable_global_baked
        and not ch.use_baked_vcol
    ):
        return rgb, alpha, height, max_height, vdisp

    baked = nodes.get(ch.baked)
    if baked:
        rgb = baked.outputs[0]

        if ch.enable_alpha:
            alpha = baked.outputs[1]

        create_link(tree, baked_uv_map, baked.inputs[0])

    if ch.type == "NORMAL":
        rgb, height, vdisp, max_height = _process_baked_normal_channel(
            tree, ch, nodes, rgb, baked_uv_map,
            end_normal_engine_filter, end_max_height
        )

    return rgb, alpha, height, max_height, vdisp


def _process_baked_normal_channel(tree, ch, nodes, rgb, baked_uv_map,
                                   end_normal_engine_filter, end_max_height):
    """
    Process baked normal channel specific connections.

    Parameters:
        tree: The node tree.
        ch: The current channel.
        nodes: The nodes in the tree.
        rgb: Current RGB value.
        baked_uv_map: Baked UV map output.
        end_normal_engine_filter: End normal engine filter node.
        end_max_height: End max height node.

    Returns:
        tuple: (rgb, height, vdisp, max_height)
    """
    baked_normal = nodes.get(ch.baked_normal)
    baked_normal_overlay = nodes.get(ch.baked_normal_overlay)
    baked_normal_prep = nodes.get(ch.baked_normal_prep)
    baked_disp = nodes.get(ch.baked_disp)
    baked_vdisp = nodes.get(ch.baked_vdisp)

    height = None
    vdisp = None
    max_height = None

    if ch.enable_subdiv_setup:
        if end_normal_engine_filter:
            if baked_normal_overlay:
                create_link(
                    tree,
                    baked_normal_overlay.outputs[0],
                    end_normal_engine_filter.inputs["Eevee"],
                )
                create_link(
                    tree,
                    baked_normal_overlay.outputs[0],
                    end_normal_engine_filter.inputs[2],
                )
            else:
                create_link(
                    tree, rgb, end_normal_engine_filter.inputs["Eevee"]
                )
                create_link(tree, rgb, end_normal_engine_filter.inputs[2])

            if rgb:
                rgb = create_link(
                    tree, rgb, end_normal_engine_filter.inputs["Cycles"]
                )[0]

    if baked_normal_prep:
        if rgb:
            rgb = create_link(tree, rgb, baked_normal_prep.inputs[0])[0]
        else:
            rgb = baked_normal_prep.outputs[0]
            break_input_link(tree, baked_normal_prep.inputs[0])

        # HACK: Some earlier nodes have wrong default color input
        baked_normal_prep.inputs[0].default_value = (0.5, 0.5, 1.0, 1.0)

    if baked_normal:
        rgb = create_link(tree, rgb, baked_normal.inputs[1])[0]

    if baked_disp:
        height = baked_disp.outputs[0]
        create_link(tree, baked_uv_map, baked_disp.inputs[0])

    if baked_vdisp:
        vdisp = baked_vdisp.outputs[0]
        create_link(tree, baked_uv_map, baked_vdisp.inputs[0])

    if end_max_height:
        max_height = end_max_height.outputs[0]

    return rgb, height, vdisp, max_height


def process_baked_vcol(tree, mp, ch, nodes, rgb, alpha):
    """
    Process baked vertex color channel.

    Parameters:
        tree: The node tree.
        mp: The MPaint data from the tree.
        ch: The current channel.
        nodes: The nodes in the tree.
        rgb: Current RGB value.
        alpha: Current alpha value.

    Returns:
        tuple: (rgb, alpha)
    """
    if not (mp.use_baked and ch.use_baked_vcol and not ch.disable_global_baked):
        return rgb, alpha

    baked_vcol = nodes.get(ch.baked_vcol)
    if baked_vcol:
        if ch.bake_to_vcol_alpha:
            rgb = baked_vcol.outputs["Alpha"]
        else:
            rgb = baked_vcol.outputs["Color"]
        if ch.enable_alpha:
            alpha = baked_vcol.outputs["Alpha"]

    return rgb, alpha


def connect_channel_to_tree_end(tree, mp, ch, rgb, alpha, height, max_height, vdisp):
    """
    Connect channel outputs to tree end node.

    Parameters:
        tree: The node tree.
        mp: The MPaint data from the tree.
        ch: The current channel.
        rgb: RGB value to connect.
        alpha: Alpha value to connect.
        height: Height value to connect.
        max_height: Max height value to connect.
        vdisp: Vector displacement value to connect.
    """
    io_name = ch.name
    io_alpha_name = ch.name + io_suffix["ALPHA"]
    io_height_name = ch.name + io_suffix["HEIGHT"]
    io_max_height_name = ch.name + io_suffix["MAX_HEIGHT"]
    io_vdisp_name = ch.name + io_suffix["VDISP"]

    create_link(tree, rgb, get_essential_node(tree, TREE_END)[io_name])

    if ch.enable_alpha:
        create_link(tree, alpha, get_essential_node(tree, TREE_END)[io_alpha_name])

    if ch.type == "NORMAL" and not ch.use_baked_vcol:
        if height and io_height_name in get_essential_node(tree, TREE_END):
            create_link(
                tree, height, get_essential_node(tree, TREE_END)[io_height_name]
            )
        if max_height and io_max_height_name in get_essential_node(tree, TREE_END):
            create_link(
                tree,
                max_height,
                get_essential_node(tree, TREE_END)[io_max_height_name],
            )
        if io_vdisp_name in get_essential_node(tree, TREE_END):
            if mp.sculpt_mode:
                create_link(
                    tree,
                    get_essential_node(tree, ZERO_VALUE)[0],
                    get_essential_node(tree, TREE_END)[io_vdisp_name],
                )
            elif vdisp:
                create_link(
                    tree, vdisp, get_essential_node(tree, TREE_END)[io_vdisp_name]
                )
