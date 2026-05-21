# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""F-curve swap operations for layers, channels, masks, and modifiers.

This module provides functions to swap F-curves between entities when reordering
them in the paint module. All swap operations update data paths to maintain
animation associations.
"""
import re

from ...utils.blender_commons import get_bpy_data
from ...utils.common import (
    get_entity_prop_input,
    get_material_fcurves_and_drivers,
    get_mp_fcurves_and_drivers,
)
from ..layer.layer_utils import get_layer_index
from ..node.node_utils import get_node_input_index


def swap_channel_fcurves(mp, idx0, idx1):
    """Swap F-curves between two channels at the specified indices.

    This function exchanges animation data between two channels by updating their data paths
    in both the MPaint tree and associated material node trees.

    Args:
        mp: The MPaint node tree object containing channels with F-curves.
        idx0 (int): Index of the first channel to swap.
        idx1 (int): Index of the second channel to swap.

    Returns:
        None
    """
    if idx0 >= len(mp.channels) or idx1 >= len(mp.channels):
        return

    # Tree fcurves
    fcurves = get_mp_fcurves_and_drivers(mp)

    for fc in fcurves:
        m = re.match(r'^mp\.channels\[(\d+)\].*', fc.data_path)
        if m:
            index = int(m.group(1))

            if index == idx0:
                fc.data_path = fc.data_path.replace(
                    'mp.channels[' + str(idx0) + ']',
                    'mp.channels[' + str(idx1) + ']'
                )

            elif index == idx1:
                fc.data_path = fc.data_path.replace(
                    'mp.channels[' + str(idx1) + ']',
                    'mp.channels[' + str(idx0) + ']'
                )

    ch0 = mp.channels[idx0]
    ch1 = mp.channels[idx1]

    ch0_idx = ch0.io_index
    ch1_idx = ch1.io_index

    # NOTE: This swap does not consider the alpha channel input
    # Since it will be replaced with dedicated channel, I think it's probably fine for now

    if idx0 > idx1 and ch1.enable_alpha:
        ch1_idx += 1

    if idx0 < idx1 and ch0.enable_alpha:
        ch0_idx += 1

    for mat in get_bpy_data().materials:
        if not mat.node_tree:
            continue

        # Get mp nodes
        mp_nodes = []
        for node in mat.node_tree.nodes:
            if node.type == 'GROUP' and node.node_tree and node.node_tree.mp == mp:
                if node not in mp_nodes:
                    mp_nodes.append(node)

        # Check for animation data
        if len(mp_nodes) > 0:
            fcurves = get_material_fcurves_and_drivers(mat)
            for node in mp_nodes:
                for fc in fcurves:
                    m = re.match(
                        r'^nodes\["' + node.name + r'"\]\.inputs\[(\d+)\]\.default_value$',
                        fc.data_path
                    )
                    if m:
                        index = int(m.group(1))
                        if index == ch0_idx:
                            fc.data_path = (
                                'nodes["' + node.name + '"].inputs['
                                + str(ch1_idx) + '].default_value'
                            )

                        elif index == ch1_idx:
                            fc.data_path = (
                                'nodes["' + node.name + '"].inputs['
                                + str(ch0_idx) + '].default_value'
                            )


def swap_layer_channel_fcurves(layer, idx0, idx1):
    """Swap F-curves between two layer channels at the specified indices.

    This function exchanges animation data between two channels within a specific layer,
    updating both property paths and node input references.

    Args:
        layer: The layer object containing channels to swap.
        idx0 (int): Index of the first layer channel to swap.
        idx1 (int): Index of the second layer channel to swap.

    Returns:
        None
    """
    if idx0 >= len(layer.channels) or idx1 >= len(layer.channels):
        return

    tree = layer.id_data
    mp = tree.mp
    fcurves = get_mp_fcurves_and_drivers(mp)
    layer_index = get_layer_index(layer)
    node = tree.nodes.get(layer.group_node)
    if not node:
        return

    for fc in fcurves:

        m1 = re.match(
            r'mp\.layers\[' + str(layer_index) + r'\]\.channels\[(\d+)\]\.(.+)',
            fc.data_path
        )
        m2 = re.match(
            r'^nodes\["' + layer.group_node + r'"\]\.inputs\[(\d+)\]\.default_value$',
            fc.data_path
        )

        index = -1
        neighbor_idx = -1
        prop_name = ''

        if m1:
            index = int(m1.group(1))
            prop_name = m1.group(2)

        elif m2:

            # Get the input
            input_index = int(m2.group(1))
            inp = node.inputs[input_index] if input_index <= len(node.inputs) else None

            if inp:

                # Get the channel index from input name
                m = re.match(r'\.channels\[(\d+)\]\.(.+)', inp.name)
                if m:
                    index = int(m.group(1))
                    prop_name = m.group(2)

        if index == idx0:
            neighbor_idx = idx1
        elif index == idx1:
            neighbor_idx = idx0

        if neighbor_idx != -1 and prop_name != '':

            # Get neighbor layer channel input
            neighbor_inp = get_entity_prop_input(layer.channels[neighbor_idx], prop_name)

            if neighbor_inp:

                # Get node input index
                neighbor_input_idx = get_node_input_index(node, neighbor_inp)
                fc.data_path = (
                    'nodes["' + layer.group_node + '"].inputs['
                    + str(neighbor_input_idx) + '].default_value'
                )

            else:
                fc.data_path = (
                    'mp.layers[' + str(layer_index) + '].channels['
                    + str(neighbor_idx) + '].' + prop_name
                )


def swap_mask_fcurves(layer, idx0, idx1):
    """Swap F-curves between two masks at the specified indices within a layer.

    This function exchanges animation data between two masks by updating their data paths
    within the layer's mask collection.

    Args:
        layer: The layer object containing masks to swap.
        idx0 (int): Index of the first mask to swap.
        idx1 (int): Index of the second mask to swap.

    Returns:
        None
    """
    mp = layer.id_data.mp
    fcurves = get_mp_fcurves_and_drivers(mp)

    for fc in fcurves:
        if layer.path_from_id() not in fc.data_path:
            continue
        m = re.match(r'mp\.layers\[(\d+)\]\.masks\[(\d+)\].*', fc.data_path)
        if m:
            index = int(m.group(2))

            if index == idx0:
                fc.data_path = fc.data_path.replace(
                    '.masks[' + str(idx0) + ']',
                    '.masks[' + str(idx1) + ']'
                )

            elif index == idx1:
                fc.data_path = fc.data_path.replace(
                    '.masks[' + str(idx1) + ']',
                    '.masks[' + str(idx0) + ']'
                )


def swap_mask_channel_fcurves(mask, idx0, idx1):
    """Swap F-curves between two mask channels at the specified indices.

    This function exchanges animation data between two channels within a specific mask
    by updating their data paths.

    Args:
        mask: The mask object containing channels to swap.
        idx0 (int): Index of the first mask channel to swap.
        idx1 (int): Index of the second mask channel to swap.

    Returns:
        None
    """
    mp = mask.id_data.mp
    fcurves = get_mp_fcurves_and_drivers(mp)

    for fc in fcurves:
        if mask.path_from_id() not in fc.data_path:
            continue
        m = re.match(
            r'mp\.layers\[(\d+)\]\.masks\[(\d+)\]\.channels\[(\d+)\].*',
            fc.data_path
        )
        if m:
            index = int(m.group(3))

            if index == idx0:
                fc.data_path = fc.data_path.replace(
                    '.channels[' + str(idx0) + ']',
                    '.channels[' + str(idx1) + ']'
                )

            elif index == idx1:
                fc.data_path = fc.data_path.replace(
                    '.channels[' + str(idx1) + ']',
                    '.channels[' + str(idx0) + ']'
                )


def swap_modifier_fcurves(parent, idx0, idx1):
    """Swap F-curves between two modifiers at the specified indices.

    This function exchanges animation data between two modifiers within a parent entity
    (layer, mask, or channel) by updating their data paths.

    Args:
        parent: The parent entity (layer, mask, or channel) containing modifiers to swap.
        idx0 (int): Index of the first modifier to swap.
        idx1 (int): Index of the second modifier to swap.

    Returns:
        None
    """
    mp = parent.id_data.mp
    fcurves = get_mp_fcurves_and_drivers(mp)

    for fc in fcurves:
        if parent.path_from_id() not in fc.data_path:
            continue
        m = re.match(r'.*\.modifiers\[(\d+)\].*', fc.data_path)
        if m:
            index = int(m.group(1))

            if index == idx0:
                fc.data_path = fc.data_path.replace(
                    '.modifiers[' + str(idx0) + ']',
                    '.modifiers[' + str(idx1) + ']'
                )

            elif index == idx1:
                fc.data_path = fc.data_path.replace(
                    '.modifiers[' + str(idx1) + ']',
                    '.modifiers[' + str(idx0) + ']'
                )


def swap_normal_modifier_fcurves(modifier, idx0, idx1):
    """Swap F-curves between two normal modifiers at the specified indices.

    This function exchanges animation data between two normal modifiers (modifiers_1 collection)
    by updating their data paths.

    Args:
        modifier: The parent entity containing normal modifiers (modifiers_1) to swap.
        idx0 (int): Index of the first normal modifier to swap.
        idx1 (int): Index of the second normal modifier to swap.

    Returns:
        None
    """
    mp = modifier.id_data.mp
    fcurves = get_mp_fcurves_and_drivers(mp)

    for fc in fcurves:
        if modifier.path_from_id() not in fc.data_path:
            continue
        m = re.match(
            r'mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers_1\[(\d+)\].*',
            fc.data_path
        )

        if m:
            index = int(m.group(3))

            if index == idx0:
                fc.data_path = fc.data_path.replace(
                    '.modifiers_1[' + str(idx0) + ']',
                    '.modifiers_1[' + str(idx1) + ']'
                )

            elif index == idx1:
                fc.data_path = fc.data_path.replace(
                    '.modifiers_1[' + str(idx1) + ']',
                    '.modifiers_1[' + str(idx0) + ']'
                )
