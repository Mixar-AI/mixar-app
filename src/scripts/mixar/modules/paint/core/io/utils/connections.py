# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ..input_outputs.inputs import (
    get_tree_input_by_name,
    get_tree_inputs,
    new_tree_input,
    remove_tree_input,
)
from ..input_outputs.outputs import (
    get_tree_output_by_name,
    get_tree_outputs,
    new_tree_output,
    remove_tree_output,
)


def match_io_between_node_tree(source, target):
    """Match and synchronize inputs and outputs between two node trees.

    This function copies inputs and outputs from a source node tree to a target node tree,
    ensuring that socket types match. It removes mismatched sockets and creates new ones
    as needed, then removes any invalid inputs/outputs that exist in the target but not
    in the source.

    Args:
        source: The source node tree to copy inputs and outputs from.
        target: The target node tree to synchronize inputs and outputs to.

    Returns:
        None
    """

    valid_inputs = []
    valid_outputs = []

    # Copy inputs
    for inp in get_tree_inputs(source):
        #target_inp = target.inputs.get(inp.name)
        target_inp = get_tree_input_by_name(target, inp.name)

        if target_inp and target_inp.bl_socket_idname != inp.bl_socket_idname:
            #target.inputs.remove(target_inp)
            remove_tree_input(target, target_inp)
            target_inp = None

        if not target_inp:
            #target_inp = target.inputs.new(inp.bl_socket_idname, inp.name)
            target_inp = new_tree_input(target, inp.name, inp.bl_socket_idname)
            target_inp.default_value = inp.default_value

        valid_inputs.append(target_inp)

    # Copy outputs
    for outp in get_tree_outputs(source):
        #target_outp = target.outputs.get(outp.name)
        target_outp = get_tree_output_by_name(target, outp.name)

        if target_outp and target_outp.bl_socket_idname != outp.bl_socket_idname:
            #target.outputs.remove(target_outp)
            remove_tree_output(target, target_outp)
            target_outp = None

        if not target_outp:
            #target_outp = target.outputs.new(outp.bl_socket_idname, outp.name)
            target_outp = new_tree_output(target, outp.name, outp.bl_socket_idname)
            target_outp.default_value = outp.default_value

        valid_outputs.append(target_outp)

    # Remove invalid inputs
    for inp in get_tree_inputs(target):
        if inp not in valid_inputs:
            #target.inputs.remove(inp)
            remove_tree_input(target, inp)

    # Remove invalid outputs
    for outp in get_tree_outputs(target):
        if outp not in valid_outputs:
            #target.outputs.remove(outp)
            remove_tree_output(target, outp)

def set_bump_backface_flip(node, flip_backface):
    """Configure bump map backface flipping for different render engines.

    This function sets the node input values for Eevee, Cycles, and Blender 2.7 Viewport
    to control bump map backface flipping behavior. The node is unmuted when this function
    is called.

    Args:
        node: The shader node to configure.
        flip_backface (bool): If True, enables backface flipping (Eevee=1.0, Cycles=1.0,
            Blender 2.7 Viewport=0.0). If False, disables it (Eevee=0.0, Cycles=0.0,
            Blender 2.7 Viewport=1.0).

    Returns:
        None
    """
    node.mute = False
    if flip_backface:
        node.inputs['Eevee'].default_value = 1.0
        node.inputs['Cycles'].default_value = 1.0
        node.inputs['Blender 2.7 Viewport'].default_value = 0.0
    else:
        node.inputs['Eevee'].default_value = 0.0
        node.inputs['Cycles'].default_value = 0.0
        node.inputs['Blender 2.7 Viewport'].default_value = 1.0

def set_normal_backface_flip(node, flip_backface):
    """Configure normal map backface flipping.

    This function sets the node's 'Flip' input value to control normal map backface
    flipping behavior. The node is unmuted when this function is called.

    Args:
        node: The shader node to configure.
        flip_backface (bool): If True, sets the 'Flip' input to 1.0. If False, sets
            it to 0.0.

    Returns:
        None
    """
    node.mute = False
    if flip_backface:
        node.inputs['Flip'].default_value = 1.0
    else:
        node.inputs['Flip'].default_value = 0.0

def set_tangent_backface_flip(node, flip_backface):
    """Configure tangent backface flipping for different render engines.

    This function sets the node input values for Eevee, Cycles, and Blender 2.7 Viewport
    to control tangent backface flipping behavior. The node is unmuted when this function
    is called.

    Args:
        node: The shader node to configure.
        flip_backface (bool): If True, enables backface flipping (Eevee=1.0, Cycles=1.0,
            Blender 2.7 Viewport=0.0). If False, disables it (Eevee=0.0, Cycles=0.0,
            Blender 2.7 Viewport=1.0).

    Returns:
        None
    """
    node.mute = False
    if flip_backface:
        node.inputs['Eevee'].default_value = 1.0
        node.inputs['Cycles'].default_value = 1.0
        node.inputs['Blender 2.7 Viewport'].default_value = 0.0
    else:
        node.inputs['Eevee'].default_value = 0.0
        node.inputs['Cycles'].default_value = 0.0
        node.inputs['Blender 2.7 Viewport'].default_value = 1.0

def set_bitangent_backface_flip(node, flip_backface):
    """Configure bitangent backface flipping.

    This function controls the mute state of a bitangent node based on whether backface
    flipping should be enabled or disabled.

    Args:
        node: The shader node to configure.
        flip_backface (bool): If True, unmutes the node. If False, mutes the node.

    Returns:
        None
    """
    if flip_backface:
        node.mute = False
    else:
        node.mute = True