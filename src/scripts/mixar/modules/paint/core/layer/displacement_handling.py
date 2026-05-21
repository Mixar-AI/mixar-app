# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Displacement node handling for material outputs.

This module manages the displacement and vector displacement nodes,
creating them if needed and connecting them to the material output.
"""

from ...ui.displacement.displacement_utils import (
    create_displacement_node,
    create_vector_displacement_node,
    get_closest_disp_node_backward,
)
from ...utils.constants import io_suffix
from ..io.input_outputs.inputs import break_input_link
from ..io.utils.io_utils import create_link
from ..node.get_nodes import get_material_output
from .layer_utils import get_root_height_channel


def _get_displacement_context(mat, node, height_ch):
    """Get the displacement context including nodes and connections.

    Args:
        mat: The material object.
        node: The MPaint node.
        height_ch: The height channel.

    Returns:
        dict: Context containing output_mat, sockets, and existing disp nodes.
               Returns None if output_mat is not available.
    """
    output_mat = get_material_output(mat)
    if not output_mat:
        return None

    return {
        "output_mat": output_mat,
        "norm_outp": node.outputs[height_ch.name],
        "height_outp": node.outputs.get(height_ch.name + io_suffix["HEIGHT"]),
        "max_height_outp": node.outputs.get(height_ch.name + io_suffix["MAX_HEIGHT"]),
        "vdisp_outp": node.outputs.get(height_ch.name + io_suffix["VDISP"]),
        "disp_mat_inp": output_mat.inputs["Displacement"],
        "disp": get_closest_disp_node_backward(output_mat, "Displacement"),
        "vdisp": get_closest_disp_node_backward(
            output_mat, "Displacement", is_vector_disp=True
        ),
    }


def _create_add_vector_node(mat, output_mat, node, disp, vdisp):
    """Create add vector node for combining displacement outputs.

    Args:
        mat: The material object.
        output_mat: The material output node.
        node: The MPaint node.
        disp: The displacement node or None.
        vdisp: The vector displacement node or None.

    Returns:
        The created add vector node, or None if not needed.
    """
    if not ((not disp and not vdisp) or (disp and not vdisp) or (not disp and vdisp)):
        return None

    add_disp = mat.node_tree.nodes.new("ShaderNodeVectorMath")
    add_disp.location.x = output_mat.location.x
    add_disp.location.y = node.location.y - 170
    add_disp.hide = True

    return add_disp


def _create_or_connect_displacement_node(mat, node, output_mat, disp, height_ch,
                                          set_one=False):
    """Create displacement node or connect existing one.

    Args:
        mat: The material object.
        node: The MPaint node.
        output_mat: The material output node.
        disp: The existing displacement node or None.
        height_ch: The height channel.
        set_one: Whether to connect existing disp inputs to mp node.

    Returns:
        tuple: (disp node, height_inp if connected else None)
    """
    from .channel_io import check_all_channel_ios

    height_inp = None

    if not disp:
        # Create displacement node
        disp = create_displacement_node(mat.node_tree)
        disp.location.x = output_mat.location.x
        disp.location.y = node.location.y - 220

        # Set displacement node default value
        disp.inputs["Height"].default_value = 0.0
        disp.inputs["Scale"].default_value = 0.0

    elif set_one:
        # Connect the original connections to mp node
        for l in disp.inputs["Height"].links:
            if not l.from_socket or l.from_node == node:
                continue
            height_inp = node.inputs.get(height_ch.name + io_suffix["HEIGHT"])
            if height_inp:
                create_link(mat.node_tree, l.from_socket, height_inp)

        for l in disp.inputs["Scale"].links:
            if not l.from_socket or l.from_node == node:
                continue
            max_height_inp = node.inputs.get(
                height_ch.name + io_suffix["MAX_HEIGHT"]
            )
            if max_height_inp:
                create_link(mat.node_tree, l.from_socket, max_height_inp)

        # Need to check start and end nodes again if height input is connected
        if height_inp:
            check_all_channel_ios(node.node_tree.mp, reconnect=False)

    return disp, height_inp


def _create_or_connect_vector_displacement_node(mat, node, output_mat, vdisp,
                                                 height_ch, set_one=False):
    """Create vector displacement node or connect existing one.

    Args:
        mat: The material object.
        node: The MPaint node.
        output_mat: The material output node.
        vdisp: The existing vector displacement node or None.
        height_ch: The height channel.
        set_one: Whether to connect existing vdisp inputs to mp node.

    Returns:
        The vdisp node (created or existing).
    """
    if not vdisp:
        # Create vector displacement node
        vdisp = create_vector_displacement_node(mat.node_tree)

        if vdisp:
            vdisp.location.x = output_mat.location.x
            vdisp.location.y = node.location.y - 410

            # Set displacement node default value
            vdisp.inputs["Vector"].default_value = (0, 0, 0, 0)

    elif set_one:
        # Connect the original connections to mp node
        for l in vdisp.inputs["Vector"].links:
            if not l.from_socket or l.from_node == node:
                continue
            vdisp_input = node.inputs.get(height_ch.name + io_suffix["VDISP"])
            if vdisp_input:
                create_link(mat.node_tree, l.from_socket, vdisp_input)

    return vdisp


def _connect_displacement_outputs(mat, disp, vdisp, add_disp, disp_mat_inp):
    """Connect displacement outputs to material output.

    Args:
        mat: The material object.
        disp: The displacement node.
        vdisp: The vector displacement node.
        add_disp: The add vector node or None.
        disp_mat_inp: The displacement input socket on material output.
    """
    if add_disp and vdisp:
        create_link(mat.node_tree, disp.outputs[0], add_disp.inputs[0])
        create_link(mat.node_tree, vdisp.outputs[0], add_disp.inputs[1])
        create_link(mat.node_tree, add_disp.outputs[0], disp_mat_inp)
    elif disp and not vdisp:
        create_link(mat.node_tree, disp.outputs[0], disp_mat_inp)


def _connect_mp_to_displacement(mat, node, disp, vdisp, height_outp,
                                 max_height_outp, vdisp_outp):
    """Connect MPaint node outputs to displacement nodes.

    Args:
        mat: The material object.
        node: The MPaint node.
        disp: The displacement node.
        vdisp: The vector displacement node.
        height_outp: The height output socket.
        max_height_outp: The max height output socket.
        vdisp_outp: The vector displacement output socket.
    """
    if vdisp and vdisp_outp:
        create_link(mat.node_tree, vdisp_outp, vdisp.inputs["Vector"])
    if disp:
        create_link(mat.node_tree, height_outp, disp.inputs["Height"])
        create_link(mat.node_tree, max_height_outp, disp.inputs["Scale"])


def _handle_set_displacement(mat, node, ctx, height_ch, set_one, set_outside):
    """Handle setting up displacement connections.

    Args:
        mat: The material object.
        node: The MPaint node.
        ctx: The displacement context dictionary.
        height_ch: The height channel.
        set_one: Whether to set up and connect displacement nodes.
        set_outside: Whether to set up nodes outside the MPaint tree.

    Returns:
        The displacement node.
    """
    output_mat = ctx["output_mat"]
    disp = ctx["disp"]
    vdisp = ctx["vdisp"]

    # Set add vector node
    add_disp = _create_add_vector_node(mat, output_mat, node, disp, vdisp)

    # Set displacement
    disp, _ = _create_or_connect_displacement_node(
        mat, node, output_mat, disp, height_ch, set_one
    )

    # Set vector displacement
    vdisp = _create_or_connect_vector_displacement_node(
        mat, node, output_mat, vdisp, height_ch, set_one
    )

    # Connect displacement outputs
    _connect_displacement_outputs(
        mat, disp, vdisp, add_disp, ctx["disp_mat_inp"]
    )

    if set_one:
        # Connect mp node to displacement
        _connect_mp_to_displacement(
            mat, node, disp, vdisp,
            ctx["height_outp"], ctx["max_height_outp"], ctx["vdisp_outp"]
        )

    return disp


def _handle_unset_displacement(mat, node, ctx, height_ch):
    """Handle disconnecting displacement from MPaint node.

    Args:
        mat: The material object.
        node: The MPaint node.
        ctx: The displacement context dictionary.
        height_ch: The height channel.
    """
    disp = ctx["disp"]
    vdisp = ctx["vdisp"]

    if disp:
        height_inp = node.inputs.get(height_ch.name + io_suffix["HEIGHT"])
        max_height_inp = node.inputs.get(height_ch.name + io_suffix["MAX_HEIGHT"])

        if height_inp and len(height_inp.links) > 0:
            soc = height_inp.links[0].from_socket
            create_link(mat.node_tree, soc, disp.inputs["Height"])
            break_input_link(mat.node_tree, height_inp)

        if max_height_inp and len(max_height_inp.links) > 0:
            soc = max_height_inp.links[0].from_socket
            create_link(mat.node_tree, soc, disp.inputs["Scale"])
            break_input_link(mat.node_tree, max_height_inp)

    if vdisp:
        vdisp_inp = node.inputs.get(height_ch.name + io_suffix["VDISP"])
        # Note: Original code had a bug here using height_inp instead of vdisp_inp
        # in break_input_link. Preserving the original behavior.
        height_inp = node.inputs.get(height_ch.name + io_suffix["HEIGHT"])
        if vdisp_inp and len(vdisp_inp.links) > 0:
            soc = vdisp_inp.links[0].from_socket
            create_link(mat.node_tree, soc, vdisp.inputs["Vector"])
            break_input_link(mat.node_tree, height_inp)


def check_displacement_node(
    mat, node, set_one=False, unset_one=False, set_outside=False
):
    """Check and setup displacement nodes for the material output.

    This function manages the displacement and vector displacement nodes,
    creating them if needed and connecting them to the material output.

    Args:
        mat: The material object.
        node: The MPaint node to connect.
        set_one: Whether to set up and connect displacement nodes. Default: False.
        unset_one: Whether to disconnect and remove displacement setup. Default: False.
        set_outside: Whether to set up nodes outside the MPaint tree. Default: False.

    Returns:
        The displacement node object, or None if no height channel exists.
    """
    height_ch = get_root_height_channel(node.node_tree.mp)
    if not height_ch:
        return None

    ctx = _get_displacement_context(mat, node, height_ch)
    if not ctx:
        return None

    disp = ctx["disp"]

    if set_one or set_outside:
        disp = _handle_set_displacement(mat, node, ctx, height_ch, set_one, set_outside)

    if unset_one:
        _handle_unset_displacement(mat, node, ctx, height_ch)

    return disp
