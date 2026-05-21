# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Property input creation functions for layer node trees.

This module handles creating input sockets for properties in layer node trees,
including property value extraction, socket type determination, and animation
data path management.
"""

import re

from mathutils import Color

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.common import get_entity_input_name
from .inputs import create_input


def create_prop_input(entity, prop_name, valid_inputs, input_index, dirty):
    """Create an input socket for a property in a layer node tree.

    This function creates an input socket for a given property of an entity (layer, channel,
    or mask). It determines the appropriate socket type based on the property type and RNA
    metadata, creates the input socket, sets default values, and updates animation data paths.

    Args:
        entity: The entity (layer, channel, or mask) containing the property.
        prop_name (str): The name of the property to create an input for.
        valid_inputs (list): List to append the created input to for validation tracking.
        input_index (int): The index position for the new input socket.
        dirty (bool): Current dirty state flag indicating if changes were made.

    Returns:
        bool: Updated dirty state - True if changes were made, False otherwise.
    """

    root_tree = entity.id_data
    mp = root_tree.mp

    m1 = re.match(r'^mp\.layers\[(\d+)\].*', entity.path_from_id())

    if m1:
        layer_index = int(m1.group(1))
        layer = mp.layers[int(layer_index)]
    else:
        return False

    # Get property rna
    entity_rna = type(entity).bl_rna
    rna = entity_rna.properties[prop_name]

    # Get prop value
    prop_value = getattr(entity, prop_name)

    # Get socket type
    if type(prop_value) == float:
        socket_type = 'NodeSocketFloat'
        if rna.subtype == 'FACTOR':
            socket_type = 'NodeSocketFloatFactor'
        default_value = rna.default
        logger.debug(f"-> Recognized as float, socket_type={socket_type}")
    elif type(prop_value) == Color:
        socket_type = 'NodeSocketColor'
        default_value = (rna.default, rna.default, rna.default, 1.0)
        logger.debug(f"-> Recognized as Color")
    elif hasattr(prop_value, '__len__') and len(prop_value) >= 3 and rna.subtype == 'COLOR':
        # FloatVector with COLOR subtype (from FloatVectorProperty)
        socket_type = 'NodeSocketColor'
        # rna.default_array gives the default values for vector properties
        if hasattr(rna, 'default_array'):
            default_value = tuple(rna.default_array) + (1.0,) if len(rna.default_array) == 3 else tuple(rna.default_array)
        else:
            default_value = (0.5, 0.5, 0.5, 1.0)
        logger.debug(f"-> Recognized as FloatVector COLOR, default_value={default_value}")
    else:
        logger.debug(f"-> NOT RECOGNIZED! Returning False")
        return False # Not implemented yet

    layer_node = root_tree.nodes.get(layer.group_node)
    tree = layer_node.node_tree
    input_name = get_entity_input_name(entity, prop_name)

    inp_dirty = create_input(
        tree, input_name, socket_type,
        valid_inputs, input_index, False,
        min_value=rna.soft_min, max_value=rna.soft_max, default_value=default_value,
        description=rna.description
    )

    # Set default value
    if inp_dirty:
        inp = layer_node.inputs.get(input_name)
        if type(prop_value) == Color:
            inp.default_value = (prop_value.r, prop_value.g, prop_value.b, 1.0)
        elif hasattr(prop_value, '__len__') and len(prop_value) >= 3 and socket_type == 'NodeSocketColor':
            # FloatVector color value
            inp.default_value = tuple(prop_value) + (1.0,) if len(prop_value) == 3 else tuple(prop_value)
        else: inp.default_value = prop_value
        dirty = True

    # Set animation data path back
    if root_tree.animation_data:
        # Example: mp.layers[0].channels[0].intensity_value'

        if root_tree.animation_data.action:
            for fc in root_tree.animation_data.action.fcurves:
                if fc.data_path == 'mp.layers[' + str(layer_index) + ']' + input_name:
                    fc.data_path = 'nodes["' + layer_node.name + '"].inputs[' + str(input_index) + '].default_value'

        for driver in root_tree.animation_data.drivers:
            if driver.data_path == 'mp.layers[' + str(layer_index) + ']' + input_name:
                driver.data_path = 'nodes["' + layer_node.name + '"].inputs[' + str(input_index) + '].default_value'

    return dirty
