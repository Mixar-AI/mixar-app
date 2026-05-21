# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""F-curve shift operations for modifiers, channels, and masks.

This module provides functions to shift F-curve indices when entities are added
or removed from collections. Shift operations update data paths to maintain
correct index references.
"""
import re

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...utils.blender_commons import get_bpy_data
from ...utils.common import (
    get_entity_prop_input,
    get_material_fcurves_and_drivers,
    get_mp_fcurves_and_drivers,
)
from ..layer.get_channels import get_layer_and_channel_prop_name_from_data_path
from ..layer.layer_utils import get_layer_index
from ..node.node_utils import get_node_input_index


def shift_modifier_fcurves_down(parent):
    """Shift all modifier F-curves down by one index position.

    This function increments the index in data paths for all modifiers, typically used
    when inserting a new modifier at the beginning of the modifier list.

    Args:
        parent: The parent entity containing modifiers whose F-curves should be shifted.

    Returns:
        None
    """
    mp = parent.id_data.mp
    fcurves = get_mp_fcurves_and_drivers(mp)

    for i, mod in reversed(list(enumerate(parent.modifiers))):
        for fc in fcurves:
            if parent.path_from_id() not in fc.data_path:
                continue
            m = re.match(r'.*\.modifiers\[(\d+)\].*', fc.data_path)
            if m and int(m.group(1)) == i:
                fc.data_path = fc.data_path.replace(
                    '.modifiers[' + str(i) + ']',
                    '.modifiers[' + str(i+1) + ']'
                )


def shift_normal_modifier_fcurves_down(parent):
    """Shift all normal modifier F-curves down by one index position.

    This function increments the index in data paths for all normal modifiers (modifiers_1),
    typically used when inserting a new normal modifier at the beginning of the list.

    Args:
        parent: The parent entity containing normal modifiers whose F-curves should be shifted.

    Returns:
        None
    """
    mp = parent.id_data.mp
    fcurves = get_mp_fcurves_and_drivers(mp)

    for i, mod in reversed(list(enumerate(parent.modifiers_1))):
        for fc in fcurves:
            if parent.path_from_id() not in fc.data_path:
                continue
            m = re.match(r'.*\.modifiers_1\[(\d+)\].*', fc.data_path)
            if m and int(m.group(1)) == i:
                fc.data_path = fc.data_path.replace(
                    '.modifiers_1[' + str(i) + ']',
                    '.modifiers_1[' + str(i+1) + ']'
                )


def shift_modifier_fcurves_up(parent, start_index=1):
    """Shift modifier F-curves up by one index position from a starting index.

    This function decrements the index in data paths for modifiers starting from the
    specified index, typically used when removing a modifier from the list.

    Args:
        parent: The parent entity containing modifiers whose F-curves should be shifted.
        start_index (int, optional): The index to start shifting from. Defaults to 1.

    Returns:
        None
    """
    tree = parent.id_data
    mp = tree.mp
    fcurves = get_mp_fcurves_and_drivers(mp)

    for i, mod in enumerate(parent.modifiers):
        if i < start_index:
            continue
        for fc in fcurves:
            if parent.path_from_id() not in fc.data_path:
                continue
            m = re.match(r'.*\.modifiers\[(\d+)\].*', fc.data_path)
            if m and int(m.group(1)) == i:
                fc.data_path = fc.data_path.replace(
                    '.modifiers[' + str(i) + ']',
                    '.modifiers[' + str(i-1) + ']'
                )


def shift_normal_modifier_fcurves_up(parent, start_index=1):
    """Shift normal modifier F-curves up by one index position from a starting index.

    This function decrements the index in data paths for normal modifiers (modifiers_1)
    starting from the specified index, typically used when removing a normal modifier.

    Args:
        parent: The parent entity containing normal modifiers whose F-curves should be shifted.
        start_index (int, optional): The index to start shifting from. Defaults to 1.

    Returns:
        None
    """
    tree = parent.id_data
    mp = tree.mp
    fcurves = get_mp_fcurves_and_drivers(mp)

    for i, mod in enumerate(parent.modifiers_1):
        if i < start_index:
            continue
        for fc in fcurves:
            if parent.path_from_id() not in fc.data_path:
                continue
            m = re.match(r'.*\.modifiers_1\[(\d+)\].*', fc.data_path)
            if m and int(m.group(1)) == i:
                fc.data_path = fc.data_path.replace(
                    '.modifiers_1[' + str(i) + ']',
                    '.modifiers_1[' + str(i-1) + ']'
                )


def shift_channel_fcurves(mp, start_index=1, direction='UP', remove_ch_mode=True):
    """Shift channel F-curves in the specified direction from a starting index.

    This function updates channel F-curve indices in both the MPaint tree and material
    node trees, handling layer channel references and alpha channel adjustments.

    Args:
        mp: The MPaint node tree object containing channels with F-curves.
        start_index (int, optional): The index to start shifting from. Defaults to 1.
        direction (str, optional): Direction to shift ('UP' or 'DOWN'). Defaults to 'UP'.
                                  'UP' decrements indices, 'DOWN' increments them.
        remove_ch_mode (bool, optional): Whether operating in channel removal mode.
                                        Affects how tree F-curves are processed. Defaults to True.

    Returns:
        None
    """
    tree = mp.id_data

    shifter = -1 if direction == 'UP' else 1

    # Tree fcurves
    if remove_ch_mode:
        fcurves = get_mp_fcurves_and_drivers(mp)

        for i, root_ch in enumerate(mp.channels):
            if i <= start_index:
                continue

            for fc in fcurves:

                layer, prop_name = get_layer_and_channel_prop_name_from_data_path(
                    mp, i, fc.data_path
                )
                if layer and prop_name != '':

                    try:
                        shifted_entity = layer.channels[i+shifter]
                    except Exception as e:
                        logger.error("Error shifting fcurves: %s", e)
                        continue

                    shifted_inp = get_entity_prop_input(shifted_entity, prop_name)
                    if shifted_inp:

                        # Get node input index
                        node = tree.nodes.get(layer.group_node)
                        shifted_input_idx = get_node_input_index(node, shifted_inp)
                        fc.data_path = (
                            'nodes["' + layer.group_node + '"].inputs['
                            + str(shifted_input_idx) + '].default_value'
                        )

                    else:
                        fc.data_path = (
                            'mp.layers[' + str(get_layer_index(layer)) + '].channels['
                            + str(i+shifter) + '].' + prop_name
                        )

                else:

                    m = re.match(r'.*\.channels\[' + str(i) + r'\].*', fc.data_path)
                    if m:
                        fc.data_path = fc.data_path.replace(
                            '.channels[' + str(i) + ']',
                            '.channels[' + str(i+shifter) + ']'
                        )

    if (remove_ch_mode and start_index < len(mp.channels)
            and mp.channels[start_index].enable_alpha and shifter < 0):
        shifter -= 1

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

                if shifter > 0:

                    for i, root_ch in reversed(list(enumerate(mp.channels))):
                        if i <= start_index:
                            continue
                        io_index = root_ch.io_index
                        for fc in fcurves:
                            m = re.match(
                                r'^nodes\["' + node.name
                                + r'"\]\.inputs\[' + str(io_index)
                                + r'\]\.default_value$',
                                fc.data_path
                            )
                            if m:
                                fc.data_path = (
                                    'nodes["' + node.name + '"].inputs['
                                    + str(io_index+shifter) + '].default_value'
                                )
                else:

                    for i, root_ch in enumerate(mp.channels):
                        if i <= start_index:
                            continue
                        io_index = root_ch.io_index
                        for fc in fcurves:
                            m = re.match(
                                r'^nodes\["' + node.name
                                + r'"\]\.inputs\[' + str(io_index)
                                + r'\]\.default_value$',
                                fc.data_path
                            )
                            if m:
                                fc.data_path = (
                                    'nodes["' + node.name + '"].inputs['
                                    + str(io_index+shifter) + '].default_value'
                                )


def shift_mask_fcurves_up(layer, start_index=1):
    """Shift mask F-curves up by one index position from a starting index.

    This function decrements the index in data paths for masks starting from the
    specified index, typically used when removing a mask from a layer.

    Args:
        layer: The layer object containing masks whose F-curves should be shifted.
        start_index (int, optional): The index to start shifting from. Defaults to 1.

    Returns:
        None
    """
    tree = layer.id_data
    mp = tree.mp
    fcurves = get_mp_fcurves_and_drivers(mp)

    for i, mask in enumerate(layer.masks):
        if i < start_index:
            continue
        for fc in fcurves:
            if layer.path_from_id() not in fc.data_path:
                continue
            m = re.match(r'.*\.masks\[(\d+)\].*', fc.data_path)
            if m and int(m.group(1)) == i:
                fc.data_path = fc.data_path.replace(
                    '.masks[' + str(i) + ']',
                    '.masks[' + str(i-1) + ']'
                )
