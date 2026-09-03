# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...node.node_utils import get_active_mpaint_node
from ..utils.io_utils import fix_tree_input_index, break_input_link

def match_group_input(node, key=None, extra_node_names=[]):
    """Match and synchronize group input values with connected nodes.

    Iterates through group input nodes and syncs their default values with
    connected sockets, ensuring consistent values throughout the node tree.

    Args:
        node: The node whose node_tree will be searched for input nodes.
        key (str, optional): Specific output socket name to process. If None,
            processes all outputs. Defaults to None.
        extra_node_names (list, optional): Additional node names to check beyond
            'Group Input'. Defaults to [].

    Returns:
        None
    """
    input_node_names = ['Group Input']
    input_node_names.extend(extra_node_names)

    for name in input_node_names:
        try:
            n = node.node_tree.nodes.get(name)
            if not key: outputs = n.outputs
            else: outputs = [n.outputs[key]]
        except: continue

        for outp in outputs:
            for link in outp.links:
                try: 
                    if link.to_socket.default_value != node.inputs[outp.name].default_value:
                        link.to_socket.default_value = node.inputs[outp.name].default_value
                except: pass

def get_tree_inputs(tree):
    """Get all input items from a node tree's interface.

    Args:
        tree: The node tree to get inputs from.

    Returns:
        list: List of all interface items that are inputs (in_out is 'INPUT' or 'BOTH').
    """
    return [ui for ui in tree.interface.items_tree if hasattr(ui, 'in_out') and ui.in_out in {'INPUT', 'BOTH'}]

def get_tree_input_by_name(tree, name):
    """Find a tree input by its name.

    Args:
        tree: The node tree to search.
        name (str): The name of the input to find.

    Returns:
        The input item if found, None otherwise.
    """
    inp = [ui for ui in tree.interface.items_tree if ui.name == name and hasattr(ui, 'in_out') and ui.in_out in {'INPUT', 'BOTH'}]
    if inp: return inp[0]

    return None

def new_tree_input(tree, name, socket_type, description='', use_both=False):
    """Create a new input socket on a node tree's interface.

    Handles special case of 'NodeSocketFloatFactor' by converting it to
    'NodeSocketFloat' with 'FACTOR' subtype.

    Args:
        tree: The node tree to add the input to.
        name (str): Name of the new input socket.
        socket_type (str): Type of the socket (e.g., 'NodeSocketFloat').
        description (str, optional): Description of the input. Defaults to ''.
        use_both (bool, optional): Currently unused parameter. Defaults to False.

    Returns:
        The newly created input socket.
    """
    subtype = 'NONE'
    if socket_type == 'NodeSocketFloatFactor':
        socket_type = 'NodeSocketFloat'
        subtype = 'FACTOR'

    inp = tree.interface.new_socket(name, description=description, in_out='INPUT', socket_type=socket_type)

    if hasattr(inp, 'subtype') and inp.subtype != subtype:
        inp.subtype = subtype
        # Blender 5.1+ re-types the interface item in place when its subtype
        # changes: same C pointer, but a different refined RNA struct, so the
        # wrapper `new_socket` returned no longer compares equal to the item
        # enumerated from `items_tree`. Callers keep the returned item in
        # `valid_inputs`, and the cleanup passes delete every input that fails
        # that membership test -- which silently removed EVERY factor input
        # (Metallic, Roughness, opacities...) right after creating it. Hand
        # back a fresh wrapper for the same item instead. Upstream Ucupaint
        # works around the same thing by deferring the subtype assignment
        # until after its cleanup pass.
        inp = refetch_interface_item(tree, inp)
    return inp


def refetch_interface_item(tree, item):
    """Return the CURRENT wrapper for `item` (matched by C pointer).

    Needed after any change that re-types an interface item (subtype,
    socket_type): the old wrapper keeps the old RNA type and fails `==`.
    """
    ptr = item.as_pointer()
    for it in tree.interface.items_tree:
        if it.as_pointer() == ptr:
            return it
    return item

def remove_tree_input(tree, item):
    """Remove an input from a node tree's interface.

    If the item is bidirectional ('BOTH'), converts it to output-only.
    If the item is input-only ('INPUT'), removes it entirely.

    Args:
        tree: The node tree containing the item.
        item: The interface item to remove.

    Returns:
        None
    """
    if item.in_out == 'BOTH':
        item.in_out = 'OUTPUT'
    elif item.in_out == 'INPUT':
        tree.interface.remove(item)

def get_tree_input_by_index(tree, index):
    """Get a tree input by its index position.

    Args:
        tree: The node tree to search.
        index (int): The zero-based index of the input to retrieve.

    Returns:
        The input item at the specified index, or None if not found.
    """
    i = -1
    for item in tree.interface.items_tree:
        if item.in_out in {'INPUT', 'BOTH'}:
            i += 1

        if i == index:
            return item

    return None

def get_neighbor_uv_space_input(texcoord_type):
    """Determine the UV space type based on texture coordinate type.

    Maps texture coordinate types to their corresponding space representation:
    - UV: Tangent Space (0.0)
    - Generated/Normal/Object: Object Space (1.0)
    - Camera/Window/Reflection: View Space (2.0)

    Args:
        texcoord_type (str): The texture coordinate type.

    Returns:
        float: 0.0 for Tangent Space, 1.0 for Object Space, 2.0 for View Space,
            or None if texcoord_type doesn't match any known type.
    """
    if texcoord_type == 'UV':
        return 0.0 # Tangent Space
    if texcoord_type in {'Generated', 'Normal', 'Object'}:
        return 1.0 # Object Space
    if texcoord_type in {'Camera', 'Window', 'Reflection'}:
        return 2.0 # View Space

def create_input(tree, name, socket_type, valid_inputs, index,
        dirty = False, min_value=None, max_value=None, default_value=None, hide_value=False, description='', node=None):
    """Create or update a tree input with specified properties.

    If the input already exists, it's added to valid_inputs. If it doesn't exist,
    creates a new input with the specified properties and sets its position in the
    interface. Sets min/max/default values if provided.

    Args:
        tree: The node tree to create the input in.
        name (str): Name of the input.
        socket_type (str): Type of the socket.
        valid_inputs (list): List to append the input to (modified in place).
        index (int): Position index for the input in the interface.
        dirty (bool, optional): Flag indicating if tree needs updating. Defaults to False.
        min_value (float, optional): Minimum value for numeric inputs. Defaults to None.
        max_value (float, optional): Maximum value for numeric inputs. Defaults to None.
        default_value: Default value for the input. Defaults to None.
        hide_value (bool, optional): Whether to hide the value in the UI. Defaults to False.
        description (str, optional): Description of the input. Defaults to ''.
        node: Optional node to set hide_value on if interface doesn't support it. Defaults to None.

    Returns:
        bool: The dirty flag, set to True if a new input was created.
    """
    inp = get_tree_input_by_name(tree, name)
    if not inp:
        inp = new_tree_input(tree, name, socket_type, description=description, use_both=True)
        dirty = True
        if min_value is not None and hasattr(inp, 'min_value'): inp.min_value = min_value
        if max_value is not None and hasattr(inp, 'max_value'): inp.max_value = max_value
        if default_value is not None: inp.default_value = default_value
        if hasattr(inp, 'hide_value'): 
            inp.hide_value = hide_value
        else:
            # NOTE: In some blender versions, hide_value is a node input prop
            if not node:
                n = get_active_mpaint_node()
                if n and n.node_tree == tree:
                    node = n
            if node:
                inpp = node.inputs.get(name)
                if inpp and hasattr(inpp, 'hide_value'):
                    inpp.hide_value = hide_value

    valid_inputs.append(inp)
    fix_tree_input_index(tree, inp, index)

    return dirty
