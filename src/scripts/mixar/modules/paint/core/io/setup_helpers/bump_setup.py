# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bump-related setup functions for layer connections.

This module provides setup functions for tangent, bitangent, and bump process
node connections during layer reconnection.
"""

from typing import TYPE_CHECKING

from ......config.logging_config import get_logger
from ....utils.constants import TREE_START, io_suffix
from ..utils.io_utils import create_link
from ...node.node_utils import get_essential_node

if TYPE_CHECKING:
    from ..layer_connections_context import LayerConnectionContext

logger = get_logger(__name__)


def setup_tangent_bitangent(ctx: "LayerConnectionContext") -> None:
    """Setup tangent and bitangent node references.

    Args:
        ctx: The LayerConnectionContext to populate with tangent/bitangent nodes.
    """
    layer = ctx.layer
    tree = ctx.tree

    ctx.layer_tangent = get_essential_node(tree, TREE_START).get(
        layer.uv_name + io_suffix["TANGENT"]
    )
    ctx.layer_bitangent = get_essential_node(tree, TREE_START).get(
        layer.uv_name + io_suffix["BITANGENT"]
    )

    if ctx.height_root_ch and ctx.height_root_ch.main_uv != "":
        ctx.tangent = get_essential_node(tree, TREE_START).get(
            ctx.height_root_ch.main_uv + io_suffix["TANGENT"]
        )
        ctx.bitangent = get_essential_node(tree, TREE_START).get(
            ctx.height_root_ch.main_uv + io_suffix["BITANGENT"]
        )
    else:
        ctx.tangent = ctx.layer_tangent
        ctx.bitangent = ctx.layer_bitangent


def setup_bump_process(ctx: "LayerConnectionContext") -> None:
    """Setup bump process node connections.

    Args:
        ctx: The LayerConnectionContext with bump_process and height_root_ch set.
    """
    if not ctx.bump_process or not ctx.height_root_ch:
        return

    tree = ctx.tree
    height_root_ch = ctx.height_root_ch
    bump_process = ctx.bump_process

    prev_normal = get_essential_node(tree, TREE_START).get(height_root_ch.name)
    prev_height = get_essential_node(tree, TREE_START).get(
        height_root_ch.name + io_suffix["HEIGHT"]
    )
    prev_max_height = get_essential_node(tree, TREE_START).get(
        height_root_ch.name + io_suffix["MAX_HEIGHT"]
    )

    if prev_height and "Height" in bump_process.inputs:
        create_link(tree, prev_height, bump_process.inputs["Height"])
    if prev_max_height and "Max Height" in bump_process.inputs:
        create_link(tree, prev_max_height, bump_process.inputs["Max Height"])

    if height_root_ch.enable_smooth_bump:
        setup_smooth_bump_heights(ctx, bump_process)

    if prev_normal:
        create_link(tree, prev_normal, bump_process.inputs["Normal Overlay"])
        ctx.prev_normal = prev_normal

    if ctx.tangent and "Tangent" in bump_process.inputs:
        create_link(tree, ctx.tangent, bump_process.inputs["Tangent"])
    if ctx.bitangent and "Bitangent" in bump_process.inputs:
        create_link(tree, ctx.bitangent, bump_process.inputs["Bitangent"])


def setup_smooth_bump_heights(ctx: "LayerConnectionContext", bump_process) -> None:
    """Setup smooth bump height connections.

    Args:
        ctx: The LayerConnectionContext with tree and height_root_ch set.
        bump_process: The bump process node to connect heights to.
    """
    tree = ctx.tree
    height_root_ch = ctx.height_root_ch

    for direction, input_name in [
        ("N", "Height N"),
        ("S", "Height S"),
        ("E", "Height E"),
        ("W", "Height W"),
    ]:
        prev_height_dir = get_essential_node(tree, TREE_START).get(
            height_root_ch.name + io_suffix[f"HEIGHT_{direction}"]
        )
        if prev_height_dir and input_name in bump_process.inputs:
            create_link(tree, prev_height_dir, bump_process.inputs[input_name])
