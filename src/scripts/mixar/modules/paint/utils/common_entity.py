# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Entity property and input utility functions for the paint module."""

import re

from mathutils import Color


def get_entity_input_name(entity, prop_name):
    """Get the input name for an entity property.

    Args:
        entity: Entity object to get input name from.
        prop_name (str): Property name to construct input name for.

    Returns:
        str: Constructed input name path, or empty string if not in a layer.
    """

    mp = entity.id_data.mp

    # Regex
    m1 = re.match(r"^mp\.layers\[(\d+)\].*", entity.path_from_id())

    if m1:
        layer_index = int(m1.group(1))
    else:
        return ""

    # Get path without layer
    path = entity.path_from_id()
    path = path.replace("mp.layers[" + str(layer_index) + "]", "")

    return path + "." + prop_name


def get_entity_prop_input(entity, prop_name):
    """Get the node input for an entity property.

    Args:
        entity: Entity object to get property input from.
        prop_name (str): Property name to get input for.

    Returns:
        Node input object if found, None otherwise.
    """
    root_tree = entity.id_data
    mp = root_tree.mp

    # Regex
    m1 = re.match(r"^mp\.layers\[(\d+)\].*", entity.path_from_id())
    if m1:
        layer_index = int(m1.group(1))
        layer = mp.layers[layer_index]
    else:
        return None

    # Get layer node
    layer_node = root_tree.nodes.get(layer.group_node)

    # Get path
    path = entity.path_from_id()
    path = path.replace("mp.layers[" + str(layer_index) + "]", "")
    path += "." + prop_name

    return layer_node.inputs.get(path)


def set_entity_prop_value(entity, prop_name, value):
    """Set the value of an entity property on both the node input and entity.

    Args:
        entity: Entity object to set property on.
        prop_name (str): Name of the property to set.
        value: Value to set (can be Color or other types).

    Returns:
        None
    """
    inp = get_entity_prop_input(entity, prop_name)
    if inp:
        if type(value) == Color:
            inp.default_value = (value.r, value.g, value.b, 1.0)
        else:
            inp.default_value = value
    setattr(entity, prop_name, value)


def get_entity_prop_value(entity, prop_name):
    """Get the value of an entity property from node input or entity attribute.

    Args:
        entity: Entity object to get property from.
        prop_name (str): Name of the property to get.

    Returns:
        The property value from node input if available, otherwise from entity attribute.
    """
    inp = get_entity_prop_input(entity, prop_name)
    if inp:
        return inp.default_value
    return getattr(entity, prop_name)
