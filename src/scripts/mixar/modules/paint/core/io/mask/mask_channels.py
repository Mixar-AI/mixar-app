# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask channel processing - handles mask channel mix connections.

This module provides functions for processing mask channels, including
root mix processing and channel mix connections with direction handling.
"""

from ....utils.common import get_entity_input_name, get_mix_color_indices
from ....utils.constants import TREE_START
from ..utils.io_utils import create_link
from ...node.node_utils import get_essential_node


def process_mask_root_mix(mask, tree, nodes, root_mask_val, mask_val):
    """Process mask root mix node.

    Args:
        mask: The mask being processed.
        tree: The node tree.
        nodes: The tree's nodes collection.
        root_mask_val: The current root mask value.
        mask_val: The mask value to mix.

    Returns:
        The updated root_mask_val after mixing.
    """
    mmix = nodes.get(mask.mix)
    if mmix:
        mixcol0, mixcol1, mixout = get_mix_color_indices(mmix)
        root_mask_val = create_link(tree, root_mask_val, mmix.inputs[mixcol0])[mixout]
        create_link(tree, mask_val, mmix.inputs[mixcol1])
    return root_mask_val


def process_mask_channels(
    mask, layer, mp, tree, nodes, mask_val,
    mask_val_n, mask_val_s, mask_val_e, mask_val_w, uv_neighbor
):
    """Process mask channel mix connections.

    Args:
        mask: The mask being processed.
        layer: The layer containing the mask.
        mp: The MPaint data structure.
        tree: The node tree.
        nodes: The tree's nodes collection.
        mask_val: The mask value.
        mask_val_n: North direction mask value.
        mask_val_s: South direction mask value.
        mask_val_e: East direction mask value.
        mask_val_w: West direction mask value.
        uv_neighbor: The UV neighbor node.
    """
    mask_intensity = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(mask, "intensity_value")
    )

    for j, c in enumerate(mask.channels):
        root_ch = mp.channels[j]
        ch = layer.channels[j]

        if not ch.enable:
            continue

        _process_single_mask_channel(
            c, ch, root_ch, mask, tree, nodes, mask_val, mask_intensity,
            mask_val_n, mask_val_s, mask_val_e, mask_val_w, uv_neighbor
        )


def _process_single_mask_channel(
    c, ch, root_ch, mask, tree, nodes, mask_val, mask_intensity,
    mask_val_n, mask_val_s, mask_val_e, mask_val_w, uv_neighbor
):
    """Process a single mask channel's mix connections.

    Args:
        c: The mask channel.
        ch: The layer channel.
        root_ch: The root channel from MPaint.
        mask: The mask being processed.
        tree: The node tree.
        nodes: The tree's nodes collection.
        mask_val: The mask value.
        mask_intensity: The mask intensity value.
        mask_val_n: North direction mask value.
        mask_val_s: South direction mask value.
        mask_val_e: East direction mask value.
        mask_val_w: West direction mask value.
        uv_neighbor: The UV neighbor node.
    """
    mask_mix = nodes.get(c.mix)
    mix_pure = nodes.get(c.mix_pure)
    mix_remains = nodes.get(c.mix_remains)
    mix_normal = nodes.get(c.mix_normal)
    mix_vdisp = nodes.get(c.mix_vdisp)

    mmixcol0, mmixcol1, mmixout = get_mix_color_indices(mask_mix)
    mp_mixcol0, mp_mixcol1, mp_mixout = get_mix_color_indices(mix_pure)
    mr_mixcol0, mr_mixcol1, mr_mixout = get_mix_color_indices(mix_remains)
    mn_mixcol0, mn_mixcol1, mn_mixout = get_mix_color_indices(mix_normal)
    mv_mixcol0, mv_mixcol1, mv_mixout = get_mix_color_indices(mix_vdisp)

    # Connect to mix_pure
    if mix_pure:
        create_link(tree, mask_val, mix_pure.inputs[mp_mixcol1])
        if mask_intensity:
            create_link(tree, mask_intensity, mix_pure.inputs[0])

    # Connect to mix_remains
    if mix_remains:
        create_link(tree, mask_val, mix_remains.inputs[mr_mixcol1])
        if mask_intensity:
            create_link(tree, mask_intensity, mix_remains.inputs[0])

    # Connect to mix_normal
    if mix_normal:
        create_link(tree, mask_val, mix_normal.inputs[mn_mixcol1])
        if mask_intensity:
            create_link(tree, mask_intensity, mix_normal.inputs[0])

    # Connect to mix_vdisp
    if mix_vdisp:
        create_link(tree, mask_val, mix_vdisp.inputs[mv_mixcol1])
        if mask_intensity:
            create_link(tree, mask_intensity, mix_vdisp.inputs[0])

    # Connect to mask_mix with direction handling
    if mask_mix:
        if mask_intensity:
            create_link(tree, mask_intensity, mask_mix.inputs[0])

        create_link(tree, mask_val, mask_mix.inputs[mmixcol1])

        _connect_mask_mix_directions(
            root_ch, mask, tree, mask_mix, mask_val,
            mask_val_n, mask_val_s, mask_val_e, mask_val_w, uv_neighbor
        )


def _connect_mask_mix_directions(
    root_ch, mask, tree, mask_mix, mask_val,
    mask_val_n, mask_val_s, mask_val_e, mask_val_w, uv_neighbor
):
    """Connect mask mix direction inputs for smooth bump.

    Args:
        root_ch: The root channel from MPaint.
        mask: The mask being processed.
        tree: The node tree.
        mask_mix: The mask mix node.
        mask_val: The mask value.
        mask_val_n: North direction mask value.
        mask_val_s: South direction mask value.
        mask_val_e: East direction mask value.
        mask_val_w: West direction mask value.
        uv_neighbor: The UV neighbor node.
    """
    if root_ch.type != "NORMAL" or not root_ch.enable_smooth_bump:
        # Regular direction connections
        if "Color2 n" in mask_mix.inputs:
            if mask_val_n:
                create_link(tree, mask_val_n, mask_mix.inputs["Color2 n"])
            else:
                create_link(tree, mask_val, mask_mix.inputs["Color2 n"])
            if mask_val_s:
                create_link(tree, mask_val_s, mask_mix.inputs["Color2 s"])
            if mask_val_e:
                create_link(tree, mask_val_e, mask_mix.inputs["Color2 e"])
            if mask_val_w:
                create_link(tree, mask_val_w, mask_mix.inputs["Color2 w"])
        return

    # Smooth bump with special types
    if not mask.use_baked and mask.type in {
        "VCOL", "HEMI", "OBJECT_INDEX", "COLOR_ID", "BACKFACE", "EDGE_DETECT", "AO"
    }:
        if uv_neighbor and "Color2 n" in mask_mix.inputs:
            create_link(tree, uv_neighbor.outputs["n"], mask_mix.inputs["Color2 n"])
            create_link(tree, uv_neighbor.outputs["s"], mask_mix.inputs["Color2 s"])
            create_link(tree, uv_neighbor.outputs["e"], mask_mix.inputs["Color2 e"])
            create_link(tree, uv_neighbor.outputs["w"], mask_mix.inputs["Color2 w"])
        elif "Color2 n" in mask_mix.inputs:
            create_link(tree, mask_val, mask_mix.inputs["Color2 n"])
            create_link(tree, mask_val, mask_mix.inputs["Color2 s"])
            create_link(tree, mask_val, mask_mix.inputs["Color2 e"])
            create_link(tree, mask_val, mask_mix.inputs["Color2 w"])
    else:
        # Regular direction connections
        if "Color2 n" in mask_mix.inputs:
            if mask_val_n:
                create_link(tree, mask_val_n, mask_mix.inputs["Color2 n"])
            else:
                create_link(tree, mask_val, mask_mix.inputs["Color2 n"])
            if mask_val_s:
                create_link(tree, mask_val_s, mask_mix.inputs["Color2 s"])
            if mask_val_e:
                create_link(tree, mask_val_e, mask_mix.inputs["Color2 e"])
            if mask_val_w:
                create_link(tree, mask_val_w, mask_mix.inputs["Color2 w"])
