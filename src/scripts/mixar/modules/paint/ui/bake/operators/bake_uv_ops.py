# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UV operations for baking"""

from ....core.io.input_outputs.outputs import get_tree_outputs
from ....core.layer.layer_utils import get_uv_layers

# Constant for active UV node name
ACTIVE_UV_NODE = "___ACTIVE_UV__"


def get_active_render_uv_node(tree, active_render_uv_name):
    """Get or create active render UV node for the given tree.

    Args:
        tree: Node tree.
        active_render_uv_name (str): Name of the active render UV map.

    Returns:
        Node: UV map node for the active render UV.
    """
    act_uv = tree.nodes.get(ACTIVE_UV_NODE)
    if not act_uv:
        act_uv = tree.nodes.new("ShaderNodeUVMap")
        act_uv.name = ACTIVE_UV_NODE
        act_uv.uv_map = active_render_uv_name

    return act_uv


def add_active_render_uv_node(tree, active_render_uv_name):
    """Add active render UV nodes to texture and texcoord nodes in tree.

    Args:
        tree: Node tree.
        active_render_uv_name (str): Name of the active render UV map.
    """
    for n in tree.nodes:
        # Check for vector input
        if n.bl_idname.startswith("ShaderNodeTex"):
            vec = n.inputs.get("Vector")
            if vec and len(vec.links) == 0:
                act_uv = get_active_render_uv_node(tree, active_render_uv_name)
                tree.links.new(act_uv.outputs[0], vec)

        # Check for texcoord node
        if n.type == "TEX_COORD":
            for l in n.outputs["UV"].links:
                act_uv = get_active_render_uv_node(tree, active_render_uv_name)
                tree.links.new(act_uv.outputs[0], l.to_socket)

        # Check for normal map
        if n.type == "NORMAL_MAP":
            n.uv_map = active_render_uv_name

        if n.type == "GROUP" and n.node_tree and not n.node_tree.mp.is_mpaint_node:
            add_active_render_uv_node(n.node_tree, active_render_uv_name)


def get_output_uv_names_from_geometry_nodes(obj):
    """Get UV layer names that are outputs from geometry nodes modifiers.

    Args:
        obj: Blender object to check.

    Returns:
        list: List of UV layer names from geometry nodes outputs.
    """

    uv_layers = get_uv_layers(obj)
    uv_names = []

    for m in obj.modifiers:
        if m.type == "NODES" and m.node_group:
            outputs = get_tree_outputs(m.node_group)
            for outp in outputs:
                if outp.socket_type == "NodeSocketVector":
                    uv = uv_layers.get(m[outp.identifier + "_attribute_name"])
                    if uv:
                        uv_names.append(uv.name)

    return uv_names
