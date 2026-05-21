# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Parallax-related setup and connection helpers for mp_connections.
"""

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.constants import (
    PARALLAX,
    BAKED_PARALLAX,
    BAKED_PARALLAX_FILTER,
    TEXCOORD,
    TEXCOORD_IO_PREFIX,
    START_UV,
    DELTA_UV,
    PARALLAX_PREP_SUFFIX,
    TREE_START,
    io_suffix,
    texcoord_lists,
)
from ...node.node_utils import get_essential_node
from ...layer.layer_utils import get_root_height_channel, get_root_parallax_channel
from ..utils.io_utils import create_link
from ..parallax.parallax_connections import reconnect_parallax_process_nodes
from ..utils.depth_connections import reconnect_depth_layer_nodes


def setup_uv_maps(mp, nodes):
    """
    Set up UV map, tangent, and bitangent dictionaries from the node tree.

    Parameters:
        mp: The MPaint data from the tree.
        nodes: The nodes in the tree.

    Returns:
        tuple: (uv_maps, tangents, bitangents) dictionaries
    """
    uv_maps = {}
    tangents = {}
    bitangents = {}

    for uv in mp.uvs:
        uv_map = nodes.get(uv.uv_map)
        if uv_map:
            uv_maps[uv.name] = uv_map.outputs[0]

        tangent_process = nodes.get(uv.tangent_process)
        if tangent_process:
            tangents[uv.name] = tangent_process.outputs["Tangent"]
            bitangents[uv.name] = tangent_process.outputs["Bitangent"]

    return uv_maps, tangents, bitangents


def get_main_tangent_bitangent(mp, tangents, bitangents):
    """
    Get the main tangent and bitangent based on height channel configuration.

    Parameters:
        mp: The MPaint data from the tree.
        tangents: Dictionary of tangent outputs.
        bitangents: Dictionary of bitangent outputs.

    Returns:
        tuple: (tangent, bitangent) outputs or (None, None)
    """
    height_ch = get_root_height_channel(mp)
    main_uv = None

    if height_ch and height_ch.main_uv != "":
        main_uv = mp.uvs.get(height_ch.main_uv)

    if not main_uv and len(mp.uvs) > 0:
        main_uv = mp.uvs[0]

    if main_uv and tangents and bitangents:
        return tangents[main_uv.name], bitangents[main_uv.name]

    return None, None


def setup_baked_uv(tree, mp, nodes):
    """
    Set up baked UV map and handle baked parallax connections.

    Parameters:
        tree: The node tree.
        mp: The MPaint data from the tree.
        nodes: The nodes in the tree.

    Returns:
        The baked UV map output (possibly filtered through parallax).
    """
    baked_uv = mp.uvs.get(mp.baked_uv_name)
    baked_uv_map = nodes.get(baked_uv.uv_map) if baked_uv else None

    if baked_uv_map:
        baked_uv_map = baked_uv_map.outputs[0]

    if mp.use_baked and baked_uv:
        parallax_ch = get_root_parallax_channel(mp)
        baked_parallax = nodes.get(BAKED_PARALLAX)
        baked_parallax_filter = nodes.get(BAKED_PARALLAX_FILTER)

        if parallax_ch and baked_parallax:
            if baked_parallax_filter:
                create_link(tree, baked_uv_map, baked_parallax_filter.inputs["Cycles"])
                create_link(
                    tree,
                    baked_parallax.outputs[0],
                    baked_parallax_filter.inputs["Eevee"],
                )
                create_link(
                    tree,
                    baked_parallax.outputs[0],
                    baked_parallax_filter.inputs["Blender 2.7 Viewport"],
                )
                baked_uv_map = baked_parallax_filter.outputs[0]
            else:
                baked_uv_map = baked_parallax.outputs[0]

    return baked_uv_map


def reconnect_parallax_nodes(tree, mp):
    """
    Reconnect parallax internal nodes including depth layer nodes.

    Parameters:
        tree: The node tree.
        mp: The MPaint data from the tree.
    """
    parallax_ch = get_root_parallax_channel(mp)
    parallax = tree.nodes.get(PARALLAX)
    baked_parallax = tree.nodes.get(BAKED_PARALLAX)

    if parallax_ch:
        if parallax:
            reconnect_parallax_process_nodes(tree, parallax)
            reconnect_depth_layer_nodes(tree, parallax_ch, parallax)
        if baked_parallax:
            reconnect_parallax_process_nodes(
                tree, baked_parallax, True, mp.baked_uv_name
            )


def reconnect_parallax_preparations(tree, mp, uv_maps, tangents, bitangents, tangent, bitangent):
    """
    Reconnect parallax preparation nodes for UV and non-UV texcoords.

    Parameters:
        tree: The node tree.
        mp: The MPaint data from the tree.
        uv_maps: Dictionary of UV map outputs.
        tangents: Dictionary of tangent outputs.
        bitangents: Dictionary of bitangent outputs.
        tangent: Main tangent output.
        bitangent: Main bitangent output.
    """
    parallax = tree.nodes.get(PARALLAX)
    baked_parallax = tree.nodes.get(BAKED_PARALLAX)

    # UV Parallax preparations
    for uv in mp.uvs:
        parallax_prep = tree.nodes.get(uv.parallax_prep)
        if parallax_prep:
            if uv.name in uv_maps:
                create_link(tree, uv_maps[uv.name], parallax_prep.inputs[0])
            if uv.name in tangents:
                create_link(tree, tangents[uv.name], parallax_prep.inputs["Tangent"])
            if uv.name in bitangents:
                create_link(
                    tree, bitangents[uv.name], parallax_prep.inputs["Bitangent"]
                )

            if parallax:
                create_link(
                    tree,
                    parallax_prep.outputs["start_uv"],
                    parallax.inputs[uv.name + START_UV],
                )
                create_link(
                    tree,
                    parallax_prep.outputs["delta_uv"],
                    parallax.inputs[uv.name + DELTA_UV],
                )

            if baked_parallax and uv.name == mp.baked_uv_name:
                create_link(
                    tree,
                    parallax_prep.outputs["start_uv"],
                    baked_parallax.inputs[uv.name + START_UV],
                )
                create_link(
                    tree,
                    parallax_prep.outputs["delta_uv"],
                    baked_parallax.inputs[uv.name + DELTA_UV],
                )

    # Non UV Parallax preparations
    for tc in texcoord_lists:
        parallax_prep = tree.nodes.get(tc + PARALLAX_PREP_SUFFIX)
        if parallax_prep:
            create_link(
                tree, get_essential_node(tree, TEXCOORD)[tc], parallax_prep.inputs[0]
            )
            if tangent and bitangent:
                create_link(tree, tangent, parallax_prep.inputs["Tangent"])
                create_link(tree, bitangent, parallax_prep.inputs["Bitangent"])

            if parallax:
                create_link(
                    tree,
                    parallax_prep.outputs["start_uv"],
                    parallax.inputs[TEXCOORD_IO_PREFIX + tc + START_UV],
                )
                create_link(
                    tree,
                    parallax_prep.outputs["delta_uv"],
                    parallax.inputs[TEXCOORD_IO_PREFIX + tc + DELTA_UV],
                )


def connect_parallax_height_inputs(tree, mp):
    """
    Connect height inputs to parallax nodes.

    Parameters:
        tree: The node tree.
        mp: The MPaint data from the tree.
    """
    parallax_ch = get_root_parallax_channel(mp)
    parallax = tree.nodes.get(PARALLAX)
    baked_parallax = tree.nodes.get(BAKED_PARALLAX)

    if parallax_ch:
        if parallax:
            height = get_essential_node(tree, TREE_START).get(
                parallax_ch.name + io_suffix["HEIGHT"]
            )
            if height:
                create_link(tree, height, parallax.inputs["base"])

        if baked_parallax:
            height = get_essential_node(tree, TREE_START).get(
                parallax_ch.name + io_suffix["HEIGHT"]
            )
            if height:
                create_link(tree, height, baked_parallax.inputs["base"])
