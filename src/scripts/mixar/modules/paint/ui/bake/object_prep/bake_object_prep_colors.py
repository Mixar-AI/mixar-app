# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Color preparation utilities for baking other objects."""

from ....core.node.get_nodes import get_material_output, get_closest_bsdf_backward
from ..utils.bake_temp_materials import get_temp_default_material


def prepare_other_objs_colors(mp, other_objs):
    """Prepare color information from other objects for baking.

    Args:
        mp: MPaint node tree property group.
        other_objs (list): List of other Blender objects.

    Returns:
        tuple: (other_mats, other_sockets, other_defaults, other_alpha_sockets,
               other_alpha_defaults, ori_mat_no_nodes) containing material and socket information.
    """

    other_mats = []
    other_sockets = []
    other_defaults = []
    other_alpha_sockets = []
    other_alpha_defaults = []

    ori_mat_no_nodes = []

    valid_bsdf_types = ["BSDF_PRINCIPLED", "BSDF_DIFFUSE", "EMISSION"]

    for o in other_objs:
        # Set new material if there's no material
        if len(o.data.materials) == 0:
            temp_mat = get_temp_default_material()
            o.data.materials.append(temp_mat)
        else:
            for i, m in enumerate(o.data.materials):
                if m is None:
                    temp_mat = get_temp_default_material()
                    o.data.materials[i] = temp_mat
                elif not m.use_nodes:
                    if m not in ori_mat_no_nodes:
                        ori_mat_no_nodes.append(m)
                    m.use_nodes = True

        for mat in o.data.materials:
            if mat is None:
                continue
            if mat in other_mats:
                continue
            if not mat.use_nodes:
                continue

            # Get material output
            output = get_material_output(mat)
            if not output:
                continue

            socket = None
            default = None
            alpha_socket = None
            alpha_default = 1.0

            if mat in ori_mat_no_nodes and hasattr(mat, "diffuse_color"):
                default = mat.diffuse_color

            # Check for possible sockets available on the bsdf node
            if not socket:
                # Search for main bsdf
                bsdf_node = get_closest_bsdf_backward(output, valid_bsdf_types)

                if bsdf_node.type == "BSDF_PRINCIPLED":
                    socket = bsdf_node.inputs["Base Color"]

                elif "Color" in bsdf_node.inputs:
                    socket = bsdf_node.inputs["Color"]

                if socket:
                    if len(socket.links) == 0:
                        if default is None:
                            default = socket.default_value
                    else:
                        socket = socket.links[0].from_socket

                # Get alpha socket
                alpha_socket = bsdf_node.inputs.get("Alpha")
                if alpha_socket:

                    if len(alpha_socket.links) == 0:
                        alpha_default = alpha_socket.default_value
                        alpha_socket = None
                    else:
                        alpha_socket = alpha_socket.links[0].from_socket

            # Append objects and materials if socket is found
            if socket or default:
                other_mats.append(mat)
                other_sockets.append(socket)
                other_defaults.append(default)
                other_alpha_sockets.append(alpha_socket)
                other_alpha_defaults.append(alpha_default)

    return (
        other_mats,
        other_sockets,
        other_defaults,
        other_alpha_sockets,
        other_alpha_defaults,
        ori_mat_no_nodes,
    )
