# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Layer iteration helpers for mp_connections.
"""

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.constants import (
    PARALLAX,
    TEXCOORD,
    TEXCOORD_IO_PREFIX,
    TREE_START,
    TREE_END,
    ZERO_VALUE,
    ONE_VALUE,
    LAYER_VIEWER,
    LAYER_ALPHA_VIEWER,
    io_suffix,
    io_names,
)
from ...node.node_utils import get_essential_node
from ...layer.check_layers import check_need_prev_normal
from ...layer.layer_utils import get_root_parallax_channel
from ..utils.io_utils import break_input_link, create_link


def process_layer_preview(tree, mp, ch, layer, layer_ch, node):
    """
    Handle layer preview mode connections.

    Parameters:
        tree: The node tree.
        mp: The MPaint data from the tree.
        ch: The current channel.
        layer: The current layer.
        layer_ch: The layer's channel data.
        node: The layer's group node.

    Returns:
        bool: True if layer should be skipped for normal processing, False otherwise.
    """
    if not mp.layer_preview_mode:
        return False

    if (
        ch == mp.channels[mp.active_channel_index]
        and layer == mp.layers[mp.active_layer_index]
    ):
        col_preview = get_essential_node(tree, TREE_END).get(LAYER_VIEWER)
        alpha_preview = get_essential_node(tree, TREE_END).get(LAYER_ALPHA_VIEWER)

        if col_preview:
            if not layer.enable:
                create_link(
                    tree,
                    get_essential_node(tree, ZERO_VALUE)[0],
                    col_preview,
                )
            else:
                create_link(tree, node.outputs[LAYER_VIEWER], col_preview)

        if alpha_preview:
            if not layer.enable:
                create_link(
                    tree,
                    get_essential_node(tree, ZERO_VALUE)[0],
                    alpha_preview,
                )
            else:
                create_link(tree, node.outputs[LAYER_ALPHA_VIEWER], alpha_preview)

        return False

    elif (
        ch.type == "NORMAL"
        and layer_ch.normal_map_type == "VECTOR_DISPLACEMENT_MAP"
    ):
        return True

    return False


def should_skip_layer(mp, layer, layer_ch, ch, merged_layer_ids, j, tree, nodes):
    """
    Determine if a layer should be skipped in processing.

    Parameters:
        mp: The MPaint data from the tree.
        layer: The current layer.
        layer_ch: The layer's channel data.
        ch: The current channel.
        merged_layer_ids: List of merged layer IDs.
        j: Current layer index.
        tree: The node tree.
        nodes: The nodes in the tree.

    Returns:
        tuple: (skip_entirely, skip_channel_processing) booleans
    """
    node = nodes.get(layer.group_node)

    # Check if layer should be completely skipped
    if (merged_layer_ids and j not in merged_layer_ids) or not layer.enable:
        if node:
            for inp in node.inputs:
                break_input_link(tree, inp)
            for outp in node.outputs:
                break_input_link(tree, outp)
        return True, True

    need_prev_normal = check_need_prev_normal(layer)

    # Check if only channel processing should be skipped
    if not (ch.type == "NORMAL" and need_prev_normal) and not layer_ch.enable:
        return False, True

    return False, False


def connect_layer_uv_inputs(tree, mp, layer, node, uv_maps, tangents, bitangents, height_ch):
    """
    Connect UV inputs to a layer node.

    Parameters:
        tree: The node tree.
        mp: The MPaint data from the tree.
        layer: The current layer.
        node: The layer's group node.
        uv_maps: Dictionary of UV map outputs.
        tangents: Dictionary of tangent outputs.
        bitangents: Dictionary of bitangent outputs.
        height_ch: The height channel.
    """
    parallax_ch = get_root_parallax_channel(mp)
    parallax = tree.nodes.get(PARALLAX)

    # Collect all UV names used by this layer
    uv_names = []

    if height_ch and height_ch.main_uv != "":
        uv_names.append(height_ch.main_uv)

    if layer.texcoord_type == "UV" and layer.uv_name not in uv_names:
        uv_names.append(layer.uv_name)

    if (
        layer.use_baked
        and layer.baked_uv_name != ""
        and layer.baked_uv_name not in uv_names
    ):
        uv_names.append(layer.baked_uv_name)

    for mask in layer.masks:
        if mask.texcoord_type == "UV" and mask.uv_name not in uv_names:
            uv_names.append(mask.uv_name)

        if (
            mask.use_baked
            and mask.baked_uv_name != ""
            and mask.baked_uv_name not in uv_names
        ):
            uv_names.append(mask.baked_uv_name)

    # Connect UV inputs
    for uv_name in uv_names:
        uv = mp.uvs.get(uv_name)
        if not uv:
            continue

        inp = node.inputs.get(uv_name + io_suffix["UV"])
        if inp:
            if parallax_ch and parallax:
                if uv_name in parallax.outputs:
                    create_link(tree, parallax.outputs[uv_name], inp)
            else:
                if uv_name in uv_maps:
                    create_link(tree, uv_maps[uv_name], inp)

        inp = node.inputs.get(uv_name + io_suffix["TANGENT"])
        if inp and uv_name in tangents:
            create_link(tree, tangents[uv_name], inp)

        inp = node.inputs.get(uv_name + io_suffix["BITANGENT"])
        if inp and uv_name in bitangents:
            create_link(tree, bitangents[uv_name], inp)


def connect_layer_texcoord_inputs(tree, mp, layer, node):
    """
    Connect texcoord inputs (non-UV) to a layer node.

    Parameters:
        tree: The node tree.
        mp: The MPaint data from the tree.
        layer: The current layer.
        node: The layer's group node.
    """
    parallax_ch = get_root_parallax_channel(mp)
    parallax = tree.nodes.get(PARALLAX)

    texcoords = []
    if layer.texcoord_type not in {"UV", "Decal"}:
        texcoords.append(layer.texcoord_type)

    for mask in layer.masks:
        if (
            mask.texcoord_type not in {"UV", "Decal", "Layer"}
            and mask.texcoord_type not in texcoords
        ):
            texcoords.append(mask.texcoord_type)

    for tc in texcoords:
        inp = node.inputs.get(io_names[tc])
        if inp:
            if parallax_ch and parallax:
                create_link(
                    tree, parallax.outputs[TEXCOORD_IO_PREFIX + tc], inp
                )
            else:
                create_link(tree, get_essential_node(tree, TEXCOORD)[tc], inp)


def connect_background_layer(tree, layer, node, ch, bg_rgb, bg_alpha, bg_height):
    """
    Connect background layer inputs.

    Parameters:
        tree: The node tree.
        layer: The current layer.
        node: The layer's group node.
        ch: The current channel.
        bg_rgb: Background RGB value.
        bg_alpha: Background alpha value.
        bg_height: Background height value.
    """
    if layer.type != "BACKGROUND":
        return

    inp = node.inputs.get(ch.name + io_suffix["BACKGROUND"])
    inp_alpha = node.inputs.get(
        ch.name + io_suffix["ALPHA"] + io_suffix["BACKGROUND"]
    )
    inp_height = node.inputs.get(
        ch.name + io_suffix["HEIGHT"] + io_suffix["BACKGROUND"]
    )

    if layer.parent_idx == -1:
        if inp:
            create_link(tree, bg_rgb, inp)
        if inp_alpha:
            create_link(tree, bg_alpha, inp_alpha)
        if inp_height:
            create_link(tree, bg_height, inp_height)
    else:
        if inp:
            break_input_link(tree, inp)
        if inp_alpha:
            break_input_link(tree, inp_alpha)
        if inp_height:
            break_input_link(tree, inp_height)


def connect_layer_channel_io(tree, node, ch, io_names_dict, channel_values):
    """
    Connect channel IO between layers.

    Parameters:
        tree: The node tree.
        node: The layer's group node.
        ch: The current channel.
        io_names_dict: Dictionary of IO names.
        channel_values: Dictionary of current channel values (rgb, alpha, height, etc.).

    Returns:
        dict: Updated channel values.
    """
    io_name = io_names_dict["io_name"]
    io_alpha_name = io_names_dict["io_alpha_name"]
    io_height_name = io_names_dict["io_height_name"]
    io_height_n_name = io_names_dict["io_height_n_name"]
    io_height_s_name = io_names_dict["io_height_s_name"]
    io_height_e_name = io_names_dict["io_height_e_name"]
    io_height_w_name = io_names_dict["io_height_w_name"]
    io_height_alpha_name = io_names_dict["io_height_alpha_name"]
    io_height_n_alpha_name = io_names_dict["io_height_n_alpha_name"]
    io_height_s_alpha_name = io_names_dict["io_height_s_alpha_name"]
    io_height_e_alpha_name = io_names_dict["io_height_e_alpha_name"]
    io_height_w_alpha_name = io_names_dict["io_height_w_alpha_name"]
    io_max_height_name = io_names_dict["io_max_height_name"]
    io_vdisp_name = io_names_dict["io_vdisp_name"]

    rgb = channel_values["rgb"]
    alpha = channel_values["alpha"]
    height = channel_values.get("height")
    height_n = channel_values.get("height_n")
    height_s = channel_values.get("height_s")
    height_e = channel_values.get("height_e")
    height_w = channel_values.get("height_w")
    height_alpha = channel_values.get("height_alpha")
    height_n_alpha = channel_values.get("height_n_alpha")
    height_s_alpha = channel_values.get("height_s_alpha")
    height_e_alpha = channel_values.get("height_e_alpha")
    height_w_alpha = channel_values.get("height_w_alpha")
    max_height = channel_values.get("max_height")
    vdisp = channel_values.get("vdisp")

    if io_name in node.inputs:
        outputs = create_link(tree, rgb, node.inputs[io_name])
        if io_name in outputs:
            rgb = outputs[io_name]

    if ch.enable_alpha and io_alpha_name in node.inputs:
        outputs = create_link(tree, alpha, node.inputs[io_alpha_name])
        if io_alpha_name in outputs:
            alpha = outputs[io_alpha_name]

    if height and io_height_name in node.inputs:
        outputs = create_link(tree, height, node.inputs[io_height_name])
        if io_height_name in outputs:
            height = outputs[io_height_name]

    if height_n and io_height_n_name in node.inputs:
        outputs = create_link(tree, height_n, node.inputs[io_height_n_name])
        if io_height_n_name in outputs:
            height_n = outputs[io_height_n_name]

    if height_s and io_height_s_name in node.inputs:
        outputs = create_link(tree, height_s, node.inputs[io_height_s_name])
        if io_height_s_name in outputs:
            height_s = outputs[io_height_s_name]

    if height_e and io_height_e_name in node.inputs:
        outputs = create_link(tree, height_e, node.inputs[io_height_e_name])
        if io_height_e_name in outputs:
            height_e = outputs[io_height_e_name]

    if height_w and io_height_w_name in node.inputs:
        outputs = create_link(tree, height_w, node.inputs[io_height_w_name])
        if io_height_w_name in outputs:
            height_w = outputs[io_height_w_name]

    if height_alpha and io_height_alpha_name in node.inputs:
        height_alpha = create_link(
            tree, height_alpha, node.inputs[io_height_alpha_name]
        )[io_height_alpha_name]

    if height_n_alpha and io_height_n_alpha_name in node.inputs:
        height_n_alpha = create_link(
            tree, height_n_alpha, node.inputs[io_height_n_alpha_name]
        )[io_height_n_alpha_name]

    if height_s_alpha and io_height_s_alpha_name in node.inputs:
        height_s_alpha = create_link(
            tree, height_s_alpha, node.inputs[io_height_s_alpha_name]
        )[io_height_s_alpha_name]

    if height_e_alpha and io_height_e_alpha_name in node.inputs:
        height_e_alpha = create_link(
            tree, height_e_alpha, node.inputs[io_height_e_alpha_name]
        )[io_height_e_alpha_name]

    if height_w_alpha and io_height_w_alpha_name in node.inputs:
        height_w_alpha = create_link(
            tree, height_w_alpha, node.inputs[io_height_w_alpha_name]
        )[io_height_w_alpha_name]

    if max_height and io_max_height_name in node.inputs:
        outps = create_link(tree, max_height, node.inputs[io_max_height_name])
        if io_max_height_name in outps:
            max_height = outps[io_max_height_name]

    if vdisp and io_vdisp_name in node.inputs:
        outps = create_link(tree, vdisp, node.inputs[io_vdisp_name])
        if io_vdisp_name in outps:
            vdisp = outps[io_vdisp_name]

    return {
        "rgb": rgb,
        "alpha": alpha,
        "height": height,
        "height_n": height_n,
        "height_s": height_s,
        "height_e": height_e,
        "height_w": height_w,
        "height_alpha": height_alpha,
        "height_n_alpha": height_n_alpha,
        "height_s_alpha": height_s_alpha,
        "height_e_alpha": height_e_alpha,
        "height_w_alpha": height_w_alpha,
        "max_height": max_height,
        "vdisp": vdisp,
    }
