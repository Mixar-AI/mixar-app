# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel preparation utilities for baking other objects."""

from ....core.node.get_nodes import (
    get_material_output,
    get_closest_bsdf_backward,
    get_closest_mp_node_backward,
)
from ....utils.constants import io_suffix
from ..utils.bake_temp_materials import (
    TEMP_MATERIAL,
    get_temp_default_material,
    remove_temp_default_material,
)


def prepare_other_objs_channels(mp, other_objs):
    """Prepare channel information from other objects for baking.

    Args:
        mp: MPaint node tree property group.
        other_objs (list): List of other Blender objects.

    Returns:
        tuple: (ch_other_objects, ch_other_mats, ch_other_sockets, ch_other_defaults,
               ch_other_default_weights, ch_other_alpha_sockets, ch_other_alpha_defaults,
               ori_mat_no_nodes) containing channel and material information.
    """
    ch_other_objects = []
    ch_other_mats = []
    ch_other_sockets = []
    ch_other_defaults = []
    ch_other_default_weights = []
    ch_other_alpha_sockets = []
    ch_other_alpha_defaults = []

    ori_mat_no_nodes = []

    valid_bsdf_types = ["BSDF_PRINCIPLED", "BSDF_DIFFUSE", "EMISSION"]

    for ch in mp.channels:
        objs = []
        mats = []
        sockets = []
        defaults = []
        default_weights = []
        alpha_sockets = []
        alpha_defaults = []

        for o in other_objs:

            # Normal channel will always use any objects
            if ch.type == "NORMAL":
                objs.append(o)
                continue

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
                # if mat in mats: continue
                if not mat.use_nodes:
                    continue

                # Get material output
                output = get_material_output(mat)
                if not output:
                    continue

                socket = None
                default = None
                default_weight = 1.0
                alpha_socket = None
                alpha_default = 1.0

                # If material originally aren't using nodes
                if mat in ori_mat_no_nodes:
                    if ch.name == "Color" and hasattr(mat, "diffuse_color"):
                        default = mat.diffuse_color
                    elif hasattr(mat, ch.name):
                        default = getattr(mat, ch.name)
                    elif hasattr(mat, ch.name.lower()):
                        default = getattr(mat, ch.name.lower())

                # Search material nodes for mp node
                mp_node = get_closest_mp_node_backward(output)
                if mp_node:
                    oyp = mp_node.node_tree.mp
                    if ch.name in oyp.channels:
                        socket = mp_node.outputs[ch.name]

                    # Check for alpha channel
                    for och in oyp.channels:
                        if och.enable_alpha:  # and och.name == ch.name:
                            alpha_socket = mp_node.outputs.get(
                                och.name + io_suffix["ALPHA"]
                            )

                # Check for possible sockets available on the bsdf node
                if not socket:
                    # Search for main bsdf
                    bsdf_node = get_closest_bsdf_backward(output, valid_bsdf_types)

                    if ch.name == "Color" and bsdf_node.type == "BSDF_PRINCIPLED":
                        socket = bsdf_node.inputs["Base Color"]

                    elif ch.name in bsdf_node.inputs:
                        socket = bsdf_node.inputs[ch.name]

                    if socket:
                        if len(socket.links) == 0:
                            if default is None:
                                default = socket.default_value

                                # Blender 4.0 has weight/strength value for some inputs
                                input_prefixes = [
                                    "Subsurface",
                                    "Coat",
                                    "Sheen",
                                    "Emission",
                                ]
                                for prefix in input_prefixes:
                                    if socket.name.startswith(prefix):

                                        if socket.name.startswith("Emission"):
                                            weight_socket_name = "Emission Strength"
                                        else:
                                            weight_socket_name = prefix + " Weight"

                                        # NOTE: Only set the default weight if there's no dedicated channel for weight in destination mp
                                        if (
                                            weight_socket_name not in mp.channels
                                            and weight_socket_name != socket.name
                                        ):
                                            weight_socket = bsdf_node.inputs.get(
                                                weight_socket_name
                                            )
                                            if weight_socket:
                                                default_weight = (
                                                    weight_socket.default_value
                                                )
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
                    mats.append(mat)
                    sockets.append(socket)
                    defaults.append(default)
                    default_weights.append(default_weight)
                    alpha_sockets.append(alpha_socket)
                    alpha_defaults.append(alpha_default)

                    if o not in objs:
                        objs.append(o)

        ch_other_objects.append(objs)
        ch_other_mats.append(mats)
        ch_other_sockets.append(sockets)
        ch_other_defaults.append(defaults)
        ch_other_default_weights.append(default_weights)
        ch_other_alpha_sockets.append(alpha_sockets)
        ch_other_alpha_defaults.append(alpha_defaults)

    return (
        ch_other_objects,
        ch_other_mats,
        ch_other_sockets,
        ch_other_defaults,
        ch_other_default_weights,
        ch_other_alpha_sockets,
        ch_other_alpha_defaults,
        ori_mat_no_nodes,
    )


def recover_other_objs_channels(other_objs, ori_mat_no_nodes):
    """Recover/restore channel state of other objects after baking.

    Args:
        other_objs (list): List of other Blender objects.
        ori_mat_no_nodes (list): List of materials that originally didn't use nodes.
    """
    for o in other_objs:
        if len(o.data.materials) == 1 and o.data.materials[0].name == TEMP_MATERIAL:
            o.data.materials.clear()
        else:
            for i, m in reversed(list(enumerate(o.data.materials))):
                if m.name == TEMP_MATERIAL:
                    o.data.materials.pop(index=i)

    for m in ori_mat_no_nodes:
        m.use_nodes = False

    remove_temp_default_material()
