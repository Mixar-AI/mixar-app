# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection normal neighbors - handles smooth bump neighbor setup.

This module provides functions for setting up neighbor RGB/alpha values
for smooth bump calculations in normal channel processing.
"""

from ......config.logging_config import get_logger
from ....utils.constants import io_suffix

logger = get_logger(__name__)


def initialize_neighbor_values(rgb, alpha_after_mod):
    """Initialize neighbor RGB and alpha values to defaults.

    Args:
        rgb: The main RGB value.
        alpha_after_mod: Alpha value after modifiers.

    Returns:
        Tuple of (rgb_n, rgb_s, rgb_e, rgb_w, alpha_n, alpha_s, alpha_e, alpha_w).
    """
    return rgb, rgb, rgb, rgb, alpha_after_mod, alpha_after_mod, alpha_after_mod, alpha_after_mod


def get_source_neighbor_nodes(nodes, layer, ch):
    """Get source neighbor nodes from layer and channel.

    Args:
        nodes: Node tree nodes.
        layer: The layer object.
        ch: The layer channel.

    Returns:
        Tuple of (source_n, source_s, source_e, source_w,
                  ch_source_n, ch_source_s, ch_source_e, ch_source_w, uv_neighbor).
    """
    source_n = nodes.get(layer.source_n) if hasattr(layer, 'source_n') else None
    source_s = nodes.get(layer.source_s) if hasattr(layer, 'source_s') else None
    source_e = nodes.get(layer.source_e) if hasattr(layer, 'source_e') else None
    source_w = nodes.get(layer.source_w) if hasattr(layer, 'source_w') else None

    ch_source_n = nodes.get(ch.source_n) if hasattr(ch, 'source_n') else None
    ch_source_s = nodes.get(ch.source_s) if hasattr(ch, 'source_s') else None
    ch_source_e = nodes.get(ch.source_e) if hasattr(ch, 'source_e') else None
    ch_source_w = nodes.get(ch.source_w) if hasattr(ch, 'source_w') else None

    uv_neighbor = nodes.get(layer.uv_neighbor) if hasattr(layer, 'uv_neighbor') else None

    return (source_n, source_s, source_e, source_w,
            ch_source_n, ch_source_s, ch_source_e, ch_source_w, uv_neighbor)


def setup_neighbor_values_from_source(
    source_n, source_s, source_e, source_w,
    ch, rgb, alpha,
    rgb_n, rgb_s, rgb_e, rgb_w,
    alpha_n, alpha_s, alpha_e, alpha_w
):
    """Set up neighbor RGB/alpha from source nodes.

    All channels use unified layer source (SP-style architecture).

    Args:
        source_n/s/e/w: Source neighbor nodes.
        ch: The layer channel.
        rgb: Current RGB value (fallback).
        alpha: Current alpha value (fallback).
        rgb_n/s/e/w: Current neighbor RGB values.
        alpha_n/s/e/w: Current neighbor alpha values.

    Returns:
        Tuple of (rgb_n, rgb_s, rgb_e, rgb_w, alpha_n, alpha_s, alpha_e, alpha_w).
    """
    if source_n and source_s and source_e and source_w:
        rgb_n = source_n.outputs[0]
        rgb_s = source_s.outputs[0]
        rgb_e = source_e.outputs[0]
        rgb_w = source_w.outputs[0]

        if len(source_n.outputs) > 1:
            alpha_n = source_n.outputs[1]
            alpha_s = source_s.outputs[1]
            alpha_e = source_e.outputs[1]
            alpha_w = source_w.outputs[1]

    return rgb_n, rgb_s, rgb_e, rgb_w, alpha_n, alpha_s, alpha_e, alpha_w


def setup_neighbor_values_from_uv(layer, uv_neighbor, rgb, alpha):
    """Set up neighbor values for VCOL, HEMI, etc. layer types using uv_neighbor.

    Args:
        layer: The layer object.
        uv_neighbor: The UV neighbor node.
        rgb: Current RGB value (fallback).
        alpha: Current alpha value (fallback).

    Returns:
        Tuple of (rgb_n, rgb_s, rgb_e, rgb_w) or None if not applicable.
    """
    if layer.type in {"VCOL", "HEMI", "OBJECT_INDEX", "EDGE_DETECT", "AO"} and uv_neighbor:
        rgb_n = uv_neighbor.outputs.get("n", rgb)
        rgb_s = uv_neighbor.outputs.get("s", rgb)
        rgb_e = uv_neighbor.outputs.get("e", rgb)
        rgb_w = uv_neighbor.outputs.get("w", rgb)
        return rgb_n, rgb_s, rgb_e, rgb_w
    return None


def setup_neighbor_values_from_group(layer, root_ch, source, rgb, alpha):
    """Set up neighbor values for GROUP layer type.

    Args:
        layer: The layer object.
        root_ch: The root channel.
        source: The source node.
        rgb: Current RGB value (fallback).
        alpha: Current alpha value (fallback).

    Returns:
        Tuple of (rgb_n, rgb_s, rgb_e, rgb_w, alpha_n, alpha_s, alpha_e, alpha_w) or None.
    """
    if layer.type == "GROUP" and root_ch.enable_smooth_bump and source:
        rgb_n = source.outputs.get(root_ch.name + io_suffix["HEIGHT_N"] + io_suffix["GROUP"], rgb)
        rgb_s = source.outputs.get(root_ch.name + io_suffix["HEIGHT_S"] + io_suffix["GROUP"], rgb)
        rgb_e = source.outputs.get(root_ch.name + io_suffix["HEIGHT_E"] + io_suffix["GROUP"], rgb)
        rgb_w = source.outputs.get(root_ch.name + io_suffix["HEIGHT_W"] + io_suffix["GROUP"], rgb)

        alpha_n = source.outputs.get(
            root_ch.name + io_suffix["HEIGHT_N"] + io_suffix["ALPHA"] + io_suffix["GROUP"], alpha
        )
        alpha_s = source.outputs.get(
            root_ch.name + io_suffix["HEIGHT_S"] + io_suffix["ALPHA"] + io_suffix["GROUP"], alpha
        )
        alpha_e = source.outputs.get(
            root_ch.name + io_suffix["HEIGHT_E"] + io_suffix["ALPHA"] + io_suffix["GROUP"], alpha
        )
        alpha_w = source.outputs.get(
            root_ch.name + io_suffix["HEIGHT_W"] + io_suffix["ALPHA"] + io_suffix["GROUP"], alpha
        )
        return rgb_n, rgb_s, rgb_e, rgb_w, alpha_n, alpha_s, alpha_e, alpha_w
    return None


def setup_neighbor_values_for_transition_bump(ch, uv_neighbor, rgb, alpha):
    """Set up neighbor values for transition bump.

    Args:
        ch: The layer channel.
        uv_neighbor: The UV neighbor node.
        rgb: Current RGB value.
        alpha: Current alpha value (fallback).

    Returns:
        Tuple of (rgb_n, rgb_s, rgb_e, rgb_w, alpha_n, alpha_s, alpha_e, alpha_w) or None.
    """
    if ch.enable_transition_bump and uv_neighbor:
        alpha_n = uv_neighbor.outputs.get("n", alpha)
        alpha_s = uv_neighbor.outputs.get("s", alpha)
        alpha_e = uv_neighbor.outputs.get("e", alpha)
        alpha_w = uv_neighbor.outputs.get("w", alpha)
        return rgb, rgb, rgb, rgb, alpha_n, alpha_s, alpha_e, alpha_w
    return None


def process_modifier_nodes_for_neighbors(tree, nodes, layer, root_ch, ch, rgb_n, rgb_s, rgb_e, rgb_w):
    """Process modifier nodes for neighbor RGB values.

    Args:
        tree: The node tree.
        nodes: Node tree nodes.
        layer: The layer object.
        root_ch: The root channel.
        ch: The layer channel.
        rgb_n/s/e/w: Neighbor RGB values.

    Returns:
        Tuple of (rgb_n, rgb_s, rgb_e, rgb_w) after modifier processing.
    """
    from ..utils.io_utils import create_link

    if layer.type != "BACKGROUND" and not (layer.type == "GROUP" and root_ch.type == "NORMAL"):
        mod_n = nodes.get(ch.mod_n) if hasattr(ch, 'mod_n') else None
        mod_s = nodes.get(ch.mod_s) if hasattr(ch, 'mod_s') else None
        mod_e = nodes.get(ch.mod_e) if hasattr(ch, 'mod_e') else None
        mod_w = nodes.get(ch.mod_w) if hasattr(ch, 'mod_w') else None

        if mod_n and rgb_n:
            rgb_n = create_link(tree, rgb_n, mod_n.inputs[0])[0]
        if mod_s and rgb_s:
            rgb_s = create_link(tree, rgb_s, mod_s.inputs[0])[0]
        if mod_e and rgb_e:
            rgb_e = create_link(tree, rgb_e, mod_e.inputs[0])[0]
        if mod_w and rgb_w:
            rgb_w = create_link(tree, rgb_w, mod_w.inputs[0])[0]

    return rgb_n, rgb_s, rgb_e, rgb_w


def setup_all_neighbor_values(ctx, ch, root_ch, rgb, alpha, alpha_after_mod):
    """Set up all neighbor values for smooth bump processing.

    This is the main entry point that coordinates all neighbor setup functions.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        rgb: Current RGB value.
        alpha: Current alpha value.
        alpha_after_mod: Alpha value after modifiers.

    Returns:
        Tuple of (rgb_n, rgb_s, rgb_e, rgb_w, alpha_n, alpha_s, alpha_e, alpha_w).
    """
    layer = ctx.layer
    tree = ctx.tree
    nodes = tree.nodes
    source = ctx.source

    # Initialize to defaults
    rgb_n, rgb_s, rgb_e, rgb_w, alpha_n, alpha_s, alpha_e, alpha_w = initialize_neighbor_values(
        rgb, alpha_after_mod
    )

    # Get source neighbor nodes
    (source_n, source_s, source_e, source_w,
     ch_source_n, ch_source_s, ch_source_e, ch_source_w, uv_neighbor) = get_source_neighbor_nodes(
        nodes, layer, ch
    )

    # Set up neighbor values from source (unified layer source - SP-style)
    source_result = setup_neighbor_values_from_source(
        source_n, source_s, source_e, source_w,
        ch, rgb, alpha,
        rgb_n, rgb_s, rgb_e, rgb_w,
        alpha_n, alpha_s, alpha_e, alpha_w
    )
    rgb_n, rgb_s, rgb_e, rgb_w, alpha_n, alpha_s, alpha_e, alpha_w = source_result

    # Check UV neighbor types for special layer types
    if not (source_n and source_s and source_e and source_w):
        uv_result = setup_neighbor_values_from_uv(layer, uv_neighbor, rgb, alpha_after_mod)
        if uv_result:
            rgb_n, rgb_s, rgb_e, rgb_w = uv_result

        group_result = setup_neighbor_values_from_group(layer, root_ch, source, rgb, alpha)
        if group_result:
            rgb_n, rgb_s, rgb_e, rgb_w, alpha_n, alpha_s, alpha_e, alpha_w = group_result

        tb_result = setup_neighbor_values_for_transition_bump(ch, uv_neighbor, rgb, alpha)
        if tb_result:
            rgb_n, rgb_s, rgb_e, rgb_w, alpha_n, alpha_s, alpha_e, alpha_w = tb_result

    # Process modifier nodes
    rgb_n, rgb_s, rgb_e, rgb_w = process_modifier_nodes_for_neighbors(
        tree, nodes, layer, root_ch, ch, rgb_n, rgb_s, rgb_e, rgb_w
    )

    return rgb_n, rgb_s, rgb_e, rgb_w, alpha_n, alpha_s, alpha_e, alpha_w
