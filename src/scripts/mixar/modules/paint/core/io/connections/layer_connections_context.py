# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection context - shared state for layer reconnection operations.

This module provides a context dataclass that holds all shared state needed
during layer node reconnection. This enables splitting the large
reconnect_layer_nodes function into smaller, more manageable helper functions.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LayerConnectionContext:
    """Holds all shared state for layer node reconnection.

    This context is populated during the setup phase and passed to
    helper functions that handle specific aspects of layer reconnection.

    Attributes:
        layer: The layer being reconnected.
        mp: The MPaint data structure.
        tree: The node tree.
        nodes: The tree's nodes collection.
        ch_idx: Channel index to reconnect (-1 for all).
        merge_mask: Whether to merge mask connections.
    """

    # Core references
    layer: Any
    mp: Any
    tree: Any
    nodes: Any
    ch_idx: int = -1
    merge_mask: bool = False

    # Source nodes
    source: Any = None
    source_group: Any = None
    baked_source: Any = None

    # Direction sources (for smooth bump)
    source_n: Any = None
    source_s: Any = None
    source_e: Any = None
    source_w: Any = None

    # UV nodes
    uv_map: Any = None
    uv_neighbor: Any = None
    uv_neighbor_1: Any = None

    # Coordinate nodes
    texcoord: Any = None
    blur_vector: Any = None
    mapping: Any = None
    linear: Any = None
    divider_alpha: Any = None
    flip_y: Any = None
    decal_process: Any = None

    # Tangent/Bitangent
    layer_tangent: Any = None
    layer_bitangent: Any = None
    tangent: Any = None
    bitangent: Any = None

    # Root channels
    height_root_ch: Any = None
    parallax_root_ch: Any = None

    # Lighting/AO
    ao_intensity: Any = None
    fake_light_intensity: Any = None
    transition_ao: Any = None
    transition_ao_power: Any = None

    # Edge detection masks
    edge_mask_n: Any = None
    edge_mask_s: Any = None
    edge_mask_e: Any = None
    edge_mask_w: Any = None

    # Normal processing
    prev_normal: Any = None
    normal_proc: Any = None
    bump_process: Any = None

    # Override channels
    override_channels: List[Any] = field(default_factory=list)

    # RGB/Alpha start values
    start_rgb: Any = None
    start_alpha: Any = None

    # Procedural material flags
    proc_is_procedural: bool = False
    proc_source_index: int = 0

    # Preview
    alpha_preview: Any = None

    # Source index for current channel
    source_index: Any = 0

    # UV neighbor color
    uv_neighbor_col: Any = None

    # Root mask value
    root_mask_val: Any = None

    # Layer intensity
    layer_intensity_value: Any = None

    # Parent flag
    has_parent: bool = False

    # Vector for texcoord
    vector: Any = None

    # Baked vector
    baked_vector: Any = None

    # Transition bump variables (set in setup, used in masks and channels)
    trans_bump_ch: Any = None
    trans_bump_flip: bool = False
    trans_bump_crease: bool = False
    chain: int = -1
    tb_value: Any = None
    tb_second_value: Any = None

    # Transition input (set during mask processing)
    transition_input: Any = None

    # End chain variables (set per-channel during mask processing)
    end_chain: Any = None
    end_chain_n: Any = None
    end_chain_s: Any = None
    end_chain_e: Any = None
    end_chain_w: Any = None
    end_chain_crease: Any = None
    end_chain_crease_n: Any = None
    end_chain_crease_s: Any = None
    end_chain_crease_e: Any = None
    end_chain_crease_w: Any = None

    # Bump smooth multiplier (used in mask and channel processing)
    bump_smooth_multiplier_value: Any = None


def create_layer_connection_context(
    layer, ch_idx: int = -1, merge_mask: bool = False
) -> LayerConnectionContext:
    """Create a new LayerConnectionContext for the given layer.

    Args:
        layer: The layer to create context for.
        ch_idx: Channel index to reconnect (-1 for all).
        merge_mask: Whether to merge mask connections.

    Returns:
        A new LayerConnectionContext instance.
    """
    from ...subtree.get_subtree import get_tree

    mp = layer.id_data.mp
    tree = get_tree(layer)
    nodes = tree.nodes

    return LayerConnectionContext(
        layer=layer,
        mp=mp,
        tree=tree,
        nodes=nodes,
        ch_idx=ch_idx,
        merge_mask=merge_mask,
    )
