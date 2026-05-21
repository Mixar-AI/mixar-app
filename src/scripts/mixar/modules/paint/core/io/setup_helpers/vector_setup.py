# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vector and texcoord setup functions for layer connections.

This module provides setup functions for baked vector, texcoord vector,
and UV neighbor connections during layer reconnection.
"""

from typing import TYPE_CHECKING

from ......config.logging_config import get_logger
from ....utils.common import get_entity_input_name
from ....utils.constants import TREE_START, io_names, io_suffix
from ..utils.io_utils import break_link, create_link
from ...layer.check_layers import is_layer_using_vector
from ...node.node_utils import get_essential_node

if TYPE_CHECKING:
    from ..layer_connections_context import LayerConnectionContext

logger = get_logger(__name__)


def setup_baked_vector(ctx: "LayerConnectionContext") -> None:
    """Setup baked vector connections.

    Args:
        ctx: The LayerConnectionContext with layer and tree set.
    """
    layer = ctx.layer
    tree = ctx.tree

    if not layer.use_baked:
        return

    ctx.baked_vector = get_essential_node(tree, TREE_START).get(
        layer.baked_uv_name + io_suffix["UV"]
    )

    if ctx.baked_vector and ctx.baked_source:
        create_link(tree, ctx.baked_vector, ctx.baked_source.inputs[0])


def setup_texcoord_vector(ctx: "LayerConnectionContext") -> None:
    """Setup texcoord vector connections.

    Args:
        ctx: The LayerConnectionContext with layer and tree set.
    """
    layer = ctx.layer
    tree = ctx.tree

    if not is_layer_using_vector(layer):
        return

    vector = None
    if layer.texcoord_type == "UV":
        vector = get_essential_node(tree, TREE_START).get(
            layer.uv_name + io_suffix["UV"]
        )
    elif layer.texcoord_type == "Decal":
        if ctx.texcoord:
            vector = ctx.texcoord.outputs["Object"]
            if ctx.decal_process:
                layer_decal_distance = get_essential_node(tree, TREE_START).get(
                    get_entity_input_name(layer, "decal_distance_value")
                )
                vector = create_link(tree, vector, ctx.decal_process.inputs[0])[0]
                if layer_decal_distance:
                    create_link(tree, layer_decal_distance, ctx.decal_process.inputs[1])
    else:
        vector = get_essential_node(tree, TREE_START).get(
            io_names[layer.texcoord_type]
        )

    if vector and ctx.blur_vector:
        vector = create_link(tree, vector, ctx.blur_vector.inputs[1])[0]
        layer_blur_factor = get_essential_node(tree, TREE_START).get(
            get_entity_input_name(layer, "blur_vector_factor")
        )
        if layer_blur_factor:
            create_link(tree, layer_blur_factor, ctx.blur_vector.inputs[0])

    if vector and ctx.mapping and layer.texcoord_type != "Decal":
        vector = create_link(tree, vector, ctx.mapping.inputs[0])[0]

    # Setup uniform scale
    uniform_scale_value = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(layer, "uniform_scale_value")
    )
    if uniform_scale_value and ctx.mapping:
        if layer.enable_uniform_scale:
            create_link(tree, uniform_scale_value, ctx.mapping.inputs[3])
        else:
            break_link(tree, uniform_scale_value, ctx.mapping.inputs[3])

    ctx.vector = vector

    # Connect vector to source and UV neighbor
    connect_vector_to_nodes(ctx, vector)


def connect_vector_to_nodes(ctx: "LayerConnectionContext", vector) -> None:
    """Connect the texcoord vector to source and UV neighbor nodes.

    Args:
        ctx: The LayerConnectionContext with layer, tree, source set.
        vector: The vector socket to connect.
    """
    if not vector:
        return

    layer = ctx.layer
    tree = ctx.tree
    source = ctx.source

    if source and "Vector" in source.inputs:
        create_link(tree, vector, source.inputs["Vector"])

    if layer.type in {
        "VCOL",
        "BACKGROUND",
        "COLOR",
        "GROUP",
        "HEMI",
        "OBJECT_INDEX",
        "EDGE_DETECT",
        "AO",
    }:
        return

    uv_neighbor = ctx.uv_neighbor
    if not uv_neighbor:
        return

    create_link(tree, vector, uv_neighbor.inputs[0])

    if ctx.tangent and "Tangent" in uv_neighbor.inputs:
        create_link(tree, ctx.tangent, uv_neighbor.inputs["Tangent"])
        create_link(tree, ctx.bitangent, uv_neighbor.inputs["Bitangent"])

    if ctx.layer_tangent:
        if "Entity Tangent" in uv_neighbor.inputs:
            create_link(tree, ctx.layer_tangent, uv_neighbor.inputs["Entity Tangent"])
            create_link(
                tree, ctx.layer_bitangent, uv_neighbor.inputs["Entity Bitangent"]
            )

        if "Mask Tangent" in uv_neighbor.inputs:
            create_link(tree, ctx.layer_tangent, uv_neighbor.inputs["Mask Tangent"])
            create_link(tree, ctx.layer_bitangent, uv_neighbor.inputs["Mask Bitangent"])

    # Connect direction sources
    if ctx.source_n:
        create_link(tree, uv_neighbor.outputs["n"], ctx.source_n.inputs[0])
    if ctx.source_s:
        create_link(tree, uv_neighbor.outputs["s"], ctx.source_s.inputs[0])
    if ctx.source_e:
        create_link(tree, uv_neighbor.outputs["e"], ctx.source_e.inputs[0])
    if ctx.source_w:
        create_link(tree, uv_neighbor.outputs["w"], ctx.source_w.inputs[0])
