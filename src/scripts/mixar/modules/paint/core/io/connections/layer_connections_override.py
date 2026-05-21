# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection override processing.

This module handles channel override and normal override operations
for layer node reconnection.
"""

from typing import TYPE_CHECKING, Any

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....utils.common import get_entity_input_name
from ....utils.constants import TREE_START, io_suffix
from ..utils.io_utils import create_link
from ...node.node_utils import get_essential_node
from ..utils.source_connections import reconnect_channel_source_internal_nodes

if TYPE_CHECKING:
    from .layer_connections_context import LayerConnectionContext


def process_channel_override(
    ctx: "LayerConnectionContext", ch, root_ch, ch_uv_neighbor, rgb: Any
) -> Any:
    """Process channel override based on override_type.

    Handles 4 override modes:
    - LAYER: Use layer's main source (rgb passed in)
    - PASSTHROUGH: Skip channel (handled upstream by get_channel_enabled)
    - OVERRIDE: Use slider value (VALUE) or color picker (RGB)
    - IMAGE: Use image texture node

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        ch_uv_neighbor: The channel UV neighbor node.
        rgb: Current RGB value (layer's main source).

    Returns:
        Updated RGB value based on override_type.
    """
    layer = ctx.layer
    mp = ctx.mp
    tree = ctx.tree
    nodes = ctx.nodes
    source = ctx.source
    vector = ctx.vector
    tangent = ctx.tangent
    bitangent = ctx.bitangent

    ch_source_group = nodes.get(ch.source_group)
    ch_source = None

    if ch_source_group:
        ch_source = ch_source_group
        reconnect_channel_source_internal_nodes(ch, ch_source_group.node_tree)
    else:
        # Handle override_type modes
        override_type = getattr(ch, 'override_type', 'LAYER')

        if override_type == "LAYER":
            # Use layer's main source - rgb is already set, no change needed
            pass

        elif override_type in ("OVERRIDE", "DEFAULT"):
            # OVERRIDE mode: Use slider/color value
            # Also handle legacy "DEFAULT" for backward compatibility
            if root_ch.type == "VALUE":
                ch_override_value = get_essential_node(tree, TREE_START).get(
                    get_entity_input_name(ch, "override_value")
                )
                if ch_override_value:
                    rgb = ch_override_value
            else:
                input_name = get_entity_input_name(ch, "override_color")
                ch_override_color = get_essential_node(tree, TREE_START).get(input_name)
                if ch_override_color:
                    rgb = ch_override_color

        elif override_type == "IMAGE":
            # IMAGE mode: Use image texture node
            ch_source = nodes.get(ch.source)

        # PASSTHROUGH is handled upstream by get_channel_enabled returning False

    if ch_source:
        if ch.override_type == "VORONOI" and ch.voronoi_feature == "N_SPHERE_RADIUS":
            rgb = ch_source.outputs["Radius"]
        else:
            rgb = ch_source.outputs[0]

    # UV neighbor connections
    if ch_uv_neighbor:
        connect_channel_uv_neighbor(ctx, ch, ch_uv_neighbor, vector, rgb)

    # Source NSEW for smooth bump
    if root_ch.type == "NORMAL" and root_ch.enable_smooth_bump and ch.override_type != "DEFAULT":
        connect_channel_direction_sources(ctx, ch, ch_uv_neighbor)

    # Connect vector to source - all channels use the layer's shared mapping
    # For fill/COLOR layers, vector might be None, so we need to get UV and route through mapping
    ch_vector = vector
    if not ch_vector and ch.override_type in {"IMAGE", "VORONOI", "NOISE", "MUSGRAVE", "WAVE", "BRICK", "CHECKER", "GRADIENT", "MAGIC", "GABOR"} and ch_source and "Vector" in ch_source.inputs:
        # Get raw UV coordinates
        raw_uv = get_essential_node(tree, TREE_START).get(
            layer.uv_name + io_suffix["UV"]
        )
        # Route through layer's mapping node if it exists
        layer_mapping = nodes.get(layer.mapping)
        if raw_uv and layer_mapping:
            # Connect UV → mapping → use mapping output
            create_link(tree, raw_uv, layer_mapping.inputs[0])
            ch_vector = layer_mapping.outputs[0]
        else:
            ch_vector = raw_uv

    if ch_vector and ch_source and ch.override_type != "DEFAULT" and "Vector" in ch_source.inputs:
        # Channel overrides use the layer's shared mapping (via ch_vector)
        # All channel images share the same UV transform
        create_link(tree, ch_vector, ch_source.inputs["Vector"])

    # Layer preview for override
    if (
        mp.layer_preview_mode
        and mp.layer_preview_mode_type == "SPECIFIC_MASK"
        and ch.active_edit == True
    ):
        if ctx.alpha_preview:
            create_link(tree, rgb, ctx.alpha_preview)

    return rgb


def connect_channel_uv_neighbor(
    ctx: "LayerConnectionContext", ch, ch_uv_neighbor, vector: Any, rgb: Any
) -> None:
    """Connect UV neighbor for channel override.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        ch_uv_neighbor: The channel UV neighbor node.
        vector: The vector socket.
        rgb: The RGB value.
    """
    tree = ctx.tree
    tangent = ctx.tangent
    bitangent = ctx.bitangent
    layer_tangent = ctx.layer_tangent
    layer_bitangent = ctx.layer_bitangent
    bump_smooth_multiplier_value = ctx.bump_smooth_multiplier_value

    if vector:
        create_link(tree, vector, ch_uv_neighbor.inputs[0])

    if ch.override_type in {"VCOL", "HEMI", "OBJECT_INDEX"}:
        create_link(tree, rgb, ch_uv_neighbor.inputs[0])

    if bump_smooth_multiplier_value and "Multiplier" in ch_uv_neighbor.inputs:
        create_link(tree, bump_smooth_multiplier_value, ch_uv_neighbor.inputs["Multiplier"])

    if tangent and "Tangent" in ch_uv_neighbor.inputs:
        create_link(tree, tangent, ch_uv_neighbor.inputs["Tangent"])
    if bitangent and "Bitangent" in ch_uv_neighbor.inputs:
        create_link(tree, bitangent, ch_uv_neighbor.inputs["Bitangent"])

    if layer_tangent:
        if "Entity Tangent" in ch_uv_neighbor.inputs:
            create_link(tree, layer_tangent, ch_uv_neighbor.inputs["Entity Tangent"])
            create_link(tree, layer_bitangent, ch_uv_neighbor.inputs["Entity Bitangent"])
        if "Mask Tangent" in ch_uv_neighbor.inputs:
            create_link(tree, layer_tangent, ch_uv_neighbor.inputs["Mask Tangent"])
            create_link(tree, layer_bitangent, ch_uv_neighbor.inputs["Mask Bitangent"])


def connect_channel_direction_sources(
    ctx: "LayerConnectionContext", ch, ch_uv_neighbor
) -> None:
    """Connect channel direction sources (N, S, E, W).

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        ch_uv_neighbor: The channel UV neighbor node.
    """
    tree = ctx.tree
    nodes = ctx.nodes

    ch_source_n = nodes.get(ch.source_n)
    ch_source_s = nodes.get(ch.source_s)
    ch_source_e = nodes.get(ch.source_e)
    ch_source_w = nodes.get(ch.source_w)

    if ch_uv_neighbor:
        if ch_source_n:
            create_link(tree, ch_uv_neighbor.outputs["n"], ch_source_n.inputs[0])
        if ch_source_s:
            create_link(tree, ch_uv_neighbor.outputs["s"], ch_source_s.inputs[0])
        if ch_source_e:
            create_link(tree, ch_uv_neighbor.outputs["e"], ch_source_e.inputs[0])
        if ch_source_w:
            create_link(tree, ch_uv_neighbor.outputs["w"], ch_source_w.inputs[0])


def process_normal_override(ctx: "LayerConnectionContext", ch, normal: Any) -> Any:
    """Process normal override for channel.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        normal: Current normal value.

    Returns:
        Updated normal value.
    """
    layer = ctx.layer
    mp = ctx.mp
    tree = ctx.tree
    nodes = ctx.nodes
    vector = ctx.vector

    if ch.override_1_type == "DEFAULT":
        ch_override_1_color = get_essential_node(tree, TREE_START).get(
            get_entity_input_name(ch, "override_1_color")
        )
        if ch_override_1_color:
            normal = ch_override_1_color
    else:
        ch_source_1 = nodes.get(ch.source_1)
        if ch_source_1:
            normal = ch_source_1.outputs[0]
            # Connect vector to source_1 - use layer's shared mapping
            src1_vector = vector
            if not src1_vector and "Vector" in ch_source_1.inputs:
                # Get raw UV and route through layer's mapping
                raw_uv = get_essential_node(tree, TREE_START).get(
                    layer.uv_name + io_suffix["UV"]
                )
                layer_mapping = nodes.get(layer.mapping)
                if raw_uv and layer_mapping:
                    create_link(tree, raw_uv, layer_mapping.inputs[0])
                    src1_vector = layer_mapping.outputs[0]
                else:
                    src1_vector = raw_uv
            if src1_vector and "Vector" in ch_source_1.inputs:
                create_link(tree, src1_vector, ch_source_1.inputs["Vector"])

    ch_linear_1 = nodes.get(ch.linear_1)
    ch_flip_y = nodes.get(ch.flip_y)

    if ch_linear_1:
        normal = create_link(tree, normal, ch_linear_1.inputs[0])[0]
    if ch_flip_y:
        normal = create_link(tree, normal, ch_flip_y.inputs[0])[0]

    # Layer preview for normal override
    if (
        mp.layer_preview_mode
        and mp.layer_preview_mode_type == "SPECIFIC_MASK"
        and ch.active_edit_1 == True
    ):
        if ctx.alpha_preview:
            create_link(tree, normal, ctx.alpha_preview)

    return normal
