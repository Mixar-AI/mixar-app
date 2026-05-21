# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for node value setting and replacement operations.

This module contains utility functions for setting node default values,
updating entity properties, managing bump base values, and replacing nodes.
"""

import re

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...utils.blender_commons import (
    get_bpy_data,
    remove_datablock,
    simple_remove_node,
)
from ...utils.common import (
    get_entity_prop_value,
    set_entity_prop_value,
)
from ..io.input_outputs.inputs import get_tree_inputs
from ..layer.mappings import get_entity_mapping
from ..node.node_utils import get_node_tree_lib, remove_tree_inside_tree
from .create_nodes import (
    new_mix_node,
    new_node,
    replace_new_node,
    simple_new_mix_node,
)


def set_default_value(node, input_name_or_index, value):
    """Set the default value for a node input.

    Sets the default value for a node input identified by either name or index.
    Handles GROUP nodes with special retry logic for nodes with missing inputs.

    Args:
        node: The Blender node to modify.
        input_name_or_index: Either an integer index or string name of the input.
        value: The value to set as the input's default value.
    """

    if node.type == 'GROUP' and not node.node_tree: return
    counter = 0
    while node.type == 'GROUP' and len(node.inputs) == 0 and counter < 64:
        logger.warning("HACK: Trying to set group '%s' again!", node.node_tree.name)
        tree_name = node.node_tree.name
        node.node_tree = get_bpy_data().node_groups.get(tree_name)
        counter += 1

    inp = None

    if type(input_name_or_index) == int:
        if input_name_or_index < len(node.inputs):
            inp = node.inputs[input_name_or_index]
    else: inp = node.inputs.get(input_name_or_index)

    if inp: inp.default_value = value
    else:
        debug_name = node.node_tree.name if node.type == 'GROUP' and node.node_tree else node.name
        logger.warning("Input '%s' in '%s' is not found!", str(input_name_or_index), debug_name)


def simple_replace_new_node(tree, node_name, node_id_name, label='', group_name='', return_status=False, hard_replace=False, dirty=False):
    """Check if node is available, replace if available.

    Checks for an existing node and replaces it if it has a different ID name.
    For GROUP nodes, handles node tree replacement and cleanup of previous trees.

    Args:
        tree: The Blender node tree to modify.
        node_name (str): The name of the node to find/create.
        node_id_name (str): The Blender ID name for the node type.
        label (str): The label to assign to the node (default: '').
        group_name (str): The name of the group tree for GROUP nodes (default: '').
        return_status (bool): Whether to return the dirty status (default: False).
        hard_replace (bool): Whether to force complete node replacement (default: False).
        dirty (bool): Initial dirty state (default: False).

    Returns:
        The node if return_status is False, otherwise a tuple of (node, dirty).
    """

    # Try to get the node first
    node = tree.nodes.get(node_name)

    # Remove node if found and has different id name
    if node and node.bl_idname != node_id_name:
        simple_remove_node(tree, node)
        node = None
        dirty = True

    # Create new node
    if not node:
        node = tree.nodes.new(node_id_name)
        node.name = node_name
        node.label = label
        dirty = True

    if node.type == 'GROUP':

        # Get previous tree
        prev_tree = node.node_tree

        # Check if group is copied
        if prev_tree:
            m = re.match(r'^' + group_name + r'_Copy\.?\d{0,3}$', prev_tree.name)
        else: m = None

        #print(prev_tree)

        if not prev_tree or (prev_tree.name != group_name and not m):

            if hard_replace:
                tree.nodes.remove(node)
                node = tree.nodes.new(node_id_name)
                node.name = node_name
                node.label = label
                dirty = True

            # Replace group tree
            node.node_tree = get_node_tree_lib(group_name)

            if not prev_tree:
                dirty = True

            else:
                # Compare previous group inputs with current group inputs
                if len(get_tree_inputs(prev_tree)) != len(node.inputs):
                    dirty = True
                else:
                    for i, inp in enumerate(node.inputs):
                        if inp.name != get_tree_inputs(prev_tree)[i].name:
                            dirty = True
                            break

                # Remove previous tree if it has no user
                if prev_tree.users == 0:
                    remove_tree_inside_tree(prev_tree)
                    remove_datablock(get_bpy_data().node_groups, prev_tree)

    if return_status:
        return node, dirty

    return node


def update_entity_uniform_scale_enabled(entity):
    """Update uniform scale settings for an entity.

    When uniform scale is enabled, sets the uniform scale value to the minimum
    axis of the regular scale. When disabled, sets all scale axes to the uniform
    scale value.

    Args:
        entity: The entity object with uniform scale properties.
    """
    if not hasattr(entity, 'enable_uniform_scale'):
        return

    mapping = get_entity_mapping(entity)
    if mapping:
        scale_input = mapping.inputs[3]

        if entity.enable_uniform_scale:
            # Set the uniform scale to min axis of regular scale when uniform scale is enabled
            set_entity_prop_value(entity, 'uniform_scale_value', min(map(abs, scale_input.default_value)))
        else:
            # Set the regular scale axes to the uniform scale when uniform scale is disabled
            scale = get_entity_prop_value(entity, 'uniform_scale_value')
            scale_input.default_value = (scale, scale, scale)


def force_bump_base_value(tree, ch, value):
    """Force set the bump base value for a channel and its neighbors.

    Sets the bump base value for the main bump node and all four neighbor
    direction nodes (north, south, east, west).

    Args:
        tree: The Blender node tree containing the bump nodes.
        ch: The channel object with bump base properties.
        value (float): The value to set for the bump base.
    """
    col = (value, value, value, 1.0)

    bump_base = tree.nodes.get(ch.bump_base)
    if bump_base: bump_base.inputs[1].default_value = col

    neighbor_directions = ['n', 's', 'e', 'w']
    for d in neighbor_directions:
        b = tree.nodes.get(getattr(ch, 'bump_base_' + d))
        if b: b.inputs[1].default_value = col


def update_bump_base_value_(tree, ch):
    """Update bump base value from channel properties.

    Wrapper function that calls force_bump_base_value with the value from
    the channel's bump_base_value property.

    Args:
        tree: The Blender node tree containing the bump nodes.
        ch: The channel object with bump_base_value property.
    """
    force_bump_base_value(tree, ch, ch.bump_base_value)


def replace_new_mix_node(tree, entity, prop, label='', return_status=False, hard_replace=False, dirty=False, force_replace=False, data_type='RGBA'):
    """Replace or create a mix node with specific data type.

    Creates or replaces a ShaderNodeMix node with the specified data type.
    This is a specialized wrapper around replace_new_node for mix nodes.

    Args:
        tree: The Blender node tree to modify.
        entity: The entity object that has a property referencing the node.
        prop (str): The property name on the entity that contains the node name.
        label (str): The label to assign to the node (default: '').
        return_status (bool): Whether to return the dirty status (default: False).
        hard_replace (bool): Whether to force complete node replacement (default: False).
        dirty (bool): Initial dirty state (default: False).
        force_replace (bool): Whether to force replacement even if node exists (default: False).
        data_type (str): The data type for the mix node (default: 'RGBA').

    Returns:
        The node if return_status is False, otherwise a tuple of (node, dirty).
    """

    node_id_name = 'ShaderNodeMix'

    group_name = ''

    node, dirty = replace_new_node(
        tree, entity, prop, node_id_name, label, group_name,
        return_status=True, hard_replace=hard_replace, dirty=dirty, force_replace=force_replace
    )

    if node.data_type != data_type:
        node.data_type = data_type

    if return_status:
        return node, dirty

    return node
