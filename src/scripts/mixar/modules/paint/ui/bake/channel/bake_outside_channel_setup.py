# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for setting up channel nodes outside the MPaint node group."""

from ....core.lib.lib import GLTF_MATERIAL_OUTPUT
from ....core.node.create_nodes import check_new_node
from ....core.node.node_utils import (
    get_node_input_index,
    get_node_tree_lib,
)
from ....utils.common import get_vcol_bl_idname, set_source_vcol_name
from ....utils.constants import io_suffix
from ...displacement.displacement_utils import (
    create_displacement_node,
    create_vector_displacement_node,
)
from ..utils.bake_common import is_baked_normal_without_bump_needed
from ..utils.bake_operators_helper import copy_default_value


def store_channel_connections(node, ch, io_suffix_dict):
    """Store original connection information for a channel.

    Args:
        node: The MPaint node.
        ch: Channel property group.
        io_suffix_dict: Dictionary of IO suffixes.
    """
    outp = node.outputs.get(ch.name)
    for l in outp.links:
        con = ch.ori_to.add()
        con.node = l.to_node.name
        con.socket = l.to_socket.name
        con.socket_index = get_node_input_index(l.to_node, l.to_socket)

    outp_alpha = node.outputs.get(ch.name + io_suffix_dict["ALPHA"])
    if outp_alpha:
        for l in outp_alpha.links:
            con = ch.ori_alpha_to.add()
            con.node = l.to_node.name
            con.socket = l.to_socket.name
            con.socket_index = get_node_input_index(l.to_node, l.to_socket)

    outp_height = node.outputs.get(ch.name + io_suffix_dict["HEIGHT"])
    if outp_height:
        for l in outp_height.links:
            con = ch.ori_height_to.add()
            con.node = l.to_node.name
            con.socket = l.to_socket.name
            con.socket_index = get_node_input_index(l.to_node, l.to_socket)

    outp_mheight = node.outputs.get(ch.name + io_suffix_dict["MAX_HEIGHT"])
    if outp_mheight:
        for l in outp_mheight.links:
            con = ch.ori_max_height_to.add()
            con.node = l.to_node.name
            con.socket = l.to_socket.name
            con.socket_index = get_node_input_index(l.to_node, l.to_socket)


def setup_vcol_node(mtree, ch, loc_x, loc_y, frame):
    """Setup vertex color node for baked outside.

    Args:
        mtree: Material node tree.
        ch: Channel property group.
        loc_x: X location for node.
        loc_y: Y location for node.
        frame: Parent frame node.

    Returns:
        tuple: (vcol node or None, updated loc_x, max_x)
    """
    max_x = loc_x
    vcol = check_new_node(mtree, ch, "baked_outside_vcol", get_vcol_bl_idname())
    set_source_vcol_name(vcol, ch.bake_to_vcol_name)
    loc_x += 280
    vcol.location.x = loc_x
    vcol.location.y = loc_y - 100
    vcol.parent = frame
    max_x = loc_x
    loc_x -= 280
    return vcol, loc_x, max_x


def setup_gltf_output(mtree, ch, tex, output_mat, shift_nodes):
    """Setup GLTF material output node for special channels.

    Args:
        mtree: Material node tree.
        ch: Channel property group.
        tex: Texture node.
        output_mat: Material output node.
        shift_nodes: List of nodes to shift.
    """
    node_name = GLTF_MATERIAL_OUTPUT
    gltf_outp = mtree.nodes.get(node_name)
    if not gltf_outp:
        gltf_outp = mtree.nodes.new("ShaderNodeGroup")
        gltf_outp.node_tree = get_node_tree_lib(node_name)
        gltf_outp.name = node_name
        gltf_outp.label = node_name
        gltf_outp.location.x = output_mat.location.x
        gltf_outp.location.y = output_mat.location.y + 200
        shift_nodes.append(gltf_outp)

    if ch.name in {"Ambient Occlusion", "Occlusion", "AO"} and "Occlusion" in gltf_outp.inputs:
        mtree.links.new(tex.outputs[0], gltf_outp.inputs["Occlusion"])
    elif ch.name == "Thickness" and "Thickness" in gltf_outp.inputs:
        mtree.links.new(tex.outputs[0], gltf_outp.inputs["Thickness"])
    elif ch.name == "Specular":
        if "Specular" in gltf_outp.inputs:
            mtree.links.new(tex.outputs[0], gltf_outp.inputs["Specular"])
        elif "specular glTF" in gltf_outp.inputs:
            mtree.links.new(tex.outputs[0], gltf_outp.inputs["specular glTF"])
    elif ch.name == "Specular Color":
        if "Specular Color" in gltf_outp.inputs:
            mtree.links.new(tex.outputs[0], gltf_outp.inputs["Specular Color"])
        elif "specularColor glTF" in gltf_outp.inputs:
            mtree.links.new(tex.outputs[0], gltf_outp.inputs["specularColor glTF"])


def process_channel_without_baked(mtree, node, ch, io_suffix_dict):
    """Process a channel without baked textures by copying default values.

    Args:
        mtree: Material node tree.
        node: MPaint node.
        ch: Channel property group.
        io_suffix_dict: Dictionary of IO suffixes.
    """
    outp = node.outputs.get(ch.name)
    outp_alpha = node.outputs.get(ch.name + io_suffix_dict["ALPHA"])
    outp_height = node.outputs.get(ch.name + io_suffix_dict["HEIGHT"])

    inp = node.inputs.get(ch.name)
    for l in outp.links:
        copy_default_value(inp, l.to_socket)

    inp_alpha = node.inputs.get(ch.name + io_suffix_dict["ALPHA"])
    if inp_alpha and outp_alpha:
        for l in outp_alpha.links:
            copy_default_value(inp_alpha, l.to_socket)

    inp_height = node.inputs.get(ch.name + io_suffix_dict["HEIGHT"])
    if inp_height and outp_height:
        for l in outp_height.links:
            copy_default_value(inp_height, l.to_socket)


def setup_regular_displacement(mtree, ch, tree, node, uv, loc_x, loc_y, frame,
                               output_mat, mat, baked_disp, disp_add, max_x):
    """Setup regular displacement node and texture.

    Args:
        mtree: Material node tree.
        ch: Channel property group.
        tree: Node tree.
        node: MPaint node.
        uv: UV map node.
        loc_x: X location for node.
        loc_y: Y location for node.
        frame: Parent frame node.
        output_mat: Material output node.
        mat: Material.
        baked_disp: Baked displacement node.
        disp_add: Displacement addition node or None.
        max_x: Current max X position.

    Returns:
        tuple: (updated loc_x, updated loc_y, max_x)
    """
    loc_y -= 300
    tex_disp = check_new_node(mtree, ch, "baked_outside_disp", "ShaderNodeTexImage")
    tex_disp.image = baked_disp.image
    tex_disp.location.x = loc_x
    tex_disp.location.y = loc_y
    tex_disp.parent = frame
    tex_disp.interpolation = "Cubic"
    mtree.links.new(uv.outputs[0], tex_disp.inputs[0])

    loc_x += 280
    disp = create_displacement_node(mat.node_tree)
    disp.location.x = loc_x
    disp.location.y = loc_y
    disp.parent = frame
    ch.baked_outside_disp_process = disp.name

    if disp_add:
        loc_x += 200
        disp_add.location.x = loc_x
        disp_add.location.y = loc_y
        disp_add.parent = frame
        max_x = loc_x
        loc_x -= 480
    else:
        max_x = loc_x
        loc_x -= 280

    mtree.links.new(tex_disp.outputs[0], disp.inputs[0])

    # Set max height
    end_max_height = node.node_tree.nodes.get(ch.end_max_height)
    if end_max_height:
        disp.inputs["Scale"].default_value = end_max_height.outputs[0].default_value

    # Target socket
    target_socket = None
    if disp_add:
        target_socket = disp_add.inputs[0]
    elif ch.enable_subdiv_setup and output_mat:
        target_socket = output_mat.inputs["Displacement"]

    # Connect to target socket
    if target_socket:
        mtree.links.new(disp.outputs[0], target_socket)

    return loc_x, loc_y, max_x


def setup_vector_displacement(mtree, ch, uv, loc_x, loc_y, frame, output_mat,
                              mat, baked_vdisp, disp_add, max_x):
    """Setup vector displacement node and texture.

    Args:
        mtree: Material node tree.
        ch: Channel property group.
        uv: UV map node.
        loc_x: X location for node.
        loc_y: Y location for node.
        frame: Parent frame node.
        output_mat: Material output node.
        mat: Material.
        baked_vdisp: Baked vector displacement node.
        disp_add: Displacement addition node or None.
        max_x: Current max X position.

    Returns:
        tuple: (updated loc_x, updated loc_y, max_x)
    """
    loc_y -= 300
    tex_vdisp = check_new_node(mtree, ch, "baked_outside_vdisp", "ShaderNodeTexImage")
    tex_vdisp.image = baked_vdisp.image
    tex_vdisp.location.x = loc_x
    tex_vdisp.location.y = loc_y
    tex_vdisp.parent = frame
    tex_vdisp.interpolation = "Cubic"
    mtree.links.new(uv.outputs[0], tex_vdisp.inputs[0])

    loc_x += 280
    vdisp = create_vector_displacement_node(mat.node_tree)
    vdisp.location.x = loc_x
    vdisp.location.y = loc_y
    vdisp.parent = frame
    ch.baked_outside_vdisp_process = vdisp.name
    max_x = loc_x
    loc_x -= 280

    mtree.links.new(tex_vdisp.outputs[0], vdisp.inputs[0])

    # Target socket
    target_socket = None
    if disp_add:
        target_socket = disp_add.inputs[1]
    elif ch.enable_subdiv_setup and output_mat:
        target_socket = output_mat.inputs["Displacement"]

    # Connect to target socket
    if target_socket:
        mtree.links.new(vdisp.outputs[0], target_socket)

    return loc_x, loc_y, max_x


def setup_displacement_nodes(mtree, mp, ch, tree, node, uv, loc_x, loc_y, frame,
                             output_mat, mat, max_x):
    """Setup displacement and vector displacement nodes.

    Args:
        mtree: Material node tree.
        mp: MPaint property group.
        ch: Channel property group.
        tree: Node tree.
        node: MPaint node.
        uv: UV map node.
        loc_x: X location for node.
        loc_y: Y location for node.
        frame: Parent frame node.
        output_mat: Material output node.
        mat: Material.
        max_x: Current max X position.

    Returns:
        tuple: (updated loc_x, updated loc_y, max_x)
    """
    baked_disp = tree.nodes.get(ch.baked_disp)
    baked_vdisp = tree.nodes.get(ch.baked_vdisp)
    disp_add = None

    # Remember original displacement connection
    if output_mat:
        for link in output_mat.inputs["Displacement"].links:
            ch.baked_outside_ori_disp_from_node = link.from_node.name
            ch.baked_outside_ori_disp_from_socket = link.from_socket.name
            break

    # Displacement addition node
    if baked_disp and baked_disp.image and baked_vdisp and baked_vdisp.image:
        disp_add = check_new_node(
            mtree, ch, "baked_outside_disp_addition", "ShaderNodeVectorMath"
        )
        if ch.enable_subdiv_setup and output_mat:
            mtree.links.new(disp_add.outputs[0], output_mat.inputs["Displacement"])

    # Setup regular displacement
    if baked_disp and baked_disp.image:
        loc_x, loc_y, max_x = setup_regular_displacement(
            mtree, ch, tree, node, uv, loc_x, loc_y, frame, output_mat,
            mat, baked_disp, disp_add, max_x
        )

    # Setup vector displacement
    if baked_vdisp and baked_vdisp.image:
        loc_x, loc_y, max_x = setup_vector_displacement(
            mtree, ch, uv, loc_x, loc_y, frame, output_mat, mat,
            baked_vdisp, disp_add, max_x
        )

    return loc_x, loc_y, max_x


def setup_normal_channel(mtree, mp, ch, tree, node, uv, loc_x, loc_y, frame,
                         tex, vcol, output_mat, mat):
    """Setup normal channel outside nodes including displacement.

    Args:
        mtree: Material node tree.
        mp: MPaint property group.
        ch: Channel property group.
        tree: Node tree.
        node: MPaint node.
        uv: UV map node.
        loc_x: X location for node.
        loc_y: Y location for node.
        frame: Parent frame node.
        tex: Texture node.
        vcol: Vertex color node or None.
        output_mat: Material output node.
        mat: Material.

    Returns:
        tuple: (updated loc_x, updated loc_y, max_x)
    """
    max_x = loc_x
    outp = node.outputs.get(ch.name)

    loc_x += 280
    norm = check_new_node(mtree, ch, "baked_outside_normal_process", "ShaderNodeNormalMap")
    norm.uv_map = mp.baked_uv_name
    norm.location.x = loc_x
    norm.location.y = loc_y
    norm.parent = frame
    max_x = loc_x
    if vcol:
        vcol.location.x += 180
        max_x = loc_x + 180
    loc_x -= 280

    mtree.links.new(tex.outputs[0], norm.inputs[1])

    # Handle normal overlay
    if is_baked_normal_without_bump_needed(ch):
        baked_normal_overlay = tree.nodes.get(ch.baked_normal_overlay)
        if baked_normal_overlay and baked_normal_overlay.image:
            loc_y -= 300
            tex_normal_overlay = check_new_node(
                mtree, ch, "baked_outside_normal_overlay", "ShaderNodeTexImage"
            )
            tex_normal_overlay.image = baked_normal_overlay.image
            tex_normal_overlay.location.x = loc_x
            tex_normal_overlay.location.y = loc_y
            tex_normal_overlay.parent = frame
            mtree.links.new(uv.outputs[0], tex_normal_overlay.inputs[0])

    for l in outp.links:
        mtree.links.new(norm.outputs[0], l.to_socket)

    # Handle displacement
    loc_x, loc_y, max_x = setup_displacement_nodes(
        mtree, mp, ch, tree, node, uv, loc_x, loc_y, frame, output_mat, mat, max_x
    )

    if ch.enable_bake_to_vcol and vcol:
        for l in outp.links:
            mtree.links.new(vcol.outputs["Color"], l.to_socket)

    return loc_x, loc_y, max_x


def process_channel_with_baked(mtree, mp, ch, tree, node, uv, loc_x, loc_y, frame,
                               output_mat, mat, baked, shift_nodes):
    """Process a channel that has baked textures.

    Args:
        mtree: Material node tree.
        mp: MPaint property group.
        ch: Channel property group.
        tree: Node tree.
        node: MPaint node.
        uv: UV map node.
        loc_x: X location for node.
        loc_y: Y location for node.
        frame: Parent frame node.
        output_mat: Material output node.
        mat: Material.
        baked: Baked texture node.
        shift_nodes: List of nodes to shift.

    Returns:
        tuple: (updated loc_x, updated loc_y, max_x)
    """
    max_x = loc_x
    outp = node.outputs.get(ch.name)
    outp_alpha = node.outputs.get(ch.name + io_suffix["ALPHA"])

    tex = check_new_node(mtree, ch, "baked_outside", "ShaderNodeTexImage")
    tex.image = baked.image
    tex.location.x = loc_x
    tex.location.y = loc_y
    tex.parent = frame
    tex.interpolation = baked.interpolation
    mtree.links.new(uv.outputs[0], tex.inputs[0])

    baked_vcol = tree.nodes.get(ch.baked_vcol)
    vcol = None
    if baked_vcol and ch.enable_bake_to_vcol:
        vcol, loc_x, max_x = setup_vcol_node(mtree, ch, loc_x, loc_y, frame)

    if outp_alpha:
        for l in outp_alpha.links:
            if vcol and ch.enable_bake_to_vcol:
                mtree.links.new(vcol.outputs["Alpha"], l.to_socket)
            else:
                mtree.links.new(tex.outputs[1], l.to_socket)

    if ch.type != "NORMAL":
        for l in outp.links:
            if vcol and ch.enable_bake_to_vcol:
                outp_name = "Alpha" if ch.bake_to_vcol_alpha else "Color"
                mtree.links.new(vcol.outputs[outp_name], l.to_socket)
            else:
                mtree.links.new(tex.outputs[0], l.to_socket)
    else:
        loc_x, loc_y, max_x = setup_normal_channel(
            mtree, mp, ch, tree, node, uv, loc_x, loc_y, frame,
            tex, vcol, output_mat, mat
        )

    loc_y -= 300

    # Create GLTF material output for special channels
    if ch.name in {"Ambient Occlusion", "Occlusion", "AO", "Specular",
                   "Specular Color", "Thickness"}:
        setup_gltf_output(mtree, ch, tex, output_mat, shift_nodes)

    return loc_x, loc_y, max_x
