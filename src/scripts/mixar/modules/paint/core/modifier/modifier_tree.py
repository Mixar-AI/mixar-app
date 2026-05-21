# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modifier tree management functions.

This module handles enabling, disabling, and checking the modifier tree
structure for layers and channels. It manages creating dedicated node groups
for modifiers when needed.
"""

import re

from ...utils.blender_commons import get_bpy_data
from ...utils.constants import MOD_TREE_END, MOD_TREE_START
from ..io.input_outputs.inputs import new_tree_input
from ..io.arrangements.layer_arrangements import rearrange_layer_nodes
from ..io.connections.layer_connections import reconnect_layer_nodes
from ..io.input_outputs.outputs import new_tree_output
from ..layer.check_layers import get_channel_enabled
from ..modifier.modifier_commons import check_modifier_nodes
from ..node.create_nodes import new_node
from ..node.node_utils import remove_node
from ..subtree.get_subtree import get_source_tree, get_tree


def check_modifiers_trees(parent, rearrange=False):
    """Check and manage the modifier tree structure for a parent layer or channel.

    Determines whether a separate modifier tree node group is needed based on the
    parent type and configuration. Enables or disables the modifier tree as appropriate,
    and ensures all modifier nodes are properly configured.

    Args:
        parent: The parent object (layer or channel) containing modifiers.
        rearrange (bool, optional): If True, reconnects and rearranges layer nodes
            after checking the modifier tree. Defaults to False.

    Returns:
        None
    """
    group_tree = parent.id_data
    mp = group_tree.mp

    enable_tree = False
    is_layer = False

    match1 = re.match(
        r"^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$", parent.path_from_id()
    )
    match2 = re.match(r"^mp\.layers\[(\d+)\]$", parent.path_from_id())

    if match1:
        layer = mp.layers[int(match1.group(1))]
        root_ch = mp.channels[int(match1.group(2))]
        ch = parent
        name = root_ch.name + " " + layer.name
        if (
            root_ch.type == "NORMAL"
            and root_ch.enable_smooth_bump
            and (
                (
                    not ch.override
                    and layer.type not in {"BACKGROUND", "COLOR", "OBJECT_INDEX"}
                )
                or (
                    ch.override
                    and ch.override_type not in {"DEFAULT"}
                    and ch.normal_map_type in {"BUMP_MAP", "BUMP_NORMAL_MAP"}
                )
            )
        ):
            enable_tree = True
        parent_tree = get_tree(layer)

    elif match2:
        layer = parent
        name = layer.name
        if layer.type not in {
            "IMAGE",
            "VCOL",
            "BACKGROUND",
            "COLOR",
            "GROUP",
            "HEMI",
            "MUSGRAVE",
        }:
            enable_tree = True
        if layer.source_group != "":
            parent_tree = get_source_tree(layer)
        else:
            parent_tree = get_tree(layer)
        is_layer = True

    else:
        parent_tree = group_tree

    if len(parent.modifiers) == 0:
        enable_tree = False

    mod_group = None
    if hasattr(parent, "mod_group"):
        mod_group = parent_tree.nodes.get(parent.mod_group)

    if enable_tree:
        if mod_group:
            for mod in parent.modifiers:
                check_modifier_nodes(mod, mod_group.node_tree)
        else:
            enable_modifiers_tree(parent, parent_tree, name, is_layer)
    else:
        if not mod_group:
            for mod in parent.modifiers:
                check_modifier_nodes(mod, parent_tree)
        else:
            disable_modifiers_tree(parent, parent_tree)

    if rearrange:
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)


def enable_modifiers_tree(
    parent, parent_tree=None, name="", is_layer=False, rearrange=False
):
    """Enable and create a dedicated node tree for modifiers.

    Creates a separate node group to contain modifier nodes when needed for complex
    layer types. This allows modifiers to process data in a dedicated tree structure
    with proper inputs and outputs.

    Args:
        parent: The parent object (layer or channel) that will have a modifier tree.
        parent_tree (optional): The parent ShaderNodeTree where the modifier group node
            will be placed. Defaults to None (auto-detected).
        name (str, optional): The name for the modifier tree. Defaults to "" (auto-generated).
        is_layer (bool, optional): Whether the parent is a layer (True) or channel (False).
            Defaults to False.
        rearrange (bool, optional): If True, reconnects and rearranges layer nodes
            after enabling the tree. Defaults to False.

    Returns:
        None
    """
    group_tree = parent.id_data
    mp = group_tree.mp

    if not parent_tree and name == "":
        match1 = re.match(
            r"^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$", parent.path_from_id()
        )
        match2 = re.match(r"^mp\.layers\[(\d+)\]$", parent.path_from_id())

        if match1:
            layer = mp.layers[int(match1.group(1))]
            root_ch = mp.channels[int(match1.group(2))]
            ch = parent
            name = root_ch.name + " " + layer.name
            if (
                layer.type in {"BACKGROUND", "COLOR", "OBJECT_INDEX"}
                and not ch.override
            ) or (ch.override and ch.override_type in {"DEFAULT"}):
                return
            parent_tree = get_tree(layer)
            is_layer = False

        elif match2:
            layer = parent
            name = layer.name
            if layer.type in {
                "IMAGE",
                "VCOL",
                "BACKGROUND",
                "COLOR",
                "GROUP",
                "HEMI",
                "MUSGRAVE",
            }:
                return
            if layer.source_group != "":
                parent_tree = get_source_tree(layer)
            else:
                parent_tree = get_tree(layer)
            is_layer = True

        else:
            return

    if len(parent.modifiers) == 0:
        return

    # Check if modifier tree already available
    if parent.mod_group != "":
        return

    # Create modifier tree
    mod_tree = get_bpy_data().node_groups.new("~yP Modifiers " + name, "ShaderNodeTree")

    new_tree_input(mod_tree, "RGB", "NodeSocketColor")
    new_tree_input(mod_tree, "Alpha", "NodeSocketFloat")
    new_tree_output(mod_tree, "RGB", "NodeSocketColor")
    new_tree_output(mod_tree, "Alpha", "NodeSocketFloat")

    # New inputs and outputs
    mod_tree_start = mod_tree.nodes.new("NodeGroupInput")
    mod_tree_start.name = MOD_TREE_START
    mod_tree_end = mod_tree.nodes.new("NodeGroupOutput")
    mod_tree_end.name = MOD_TREE_END

    # Create main modifier group
    mod_group = new_node(
        parent_tree, parent, "mod_group", "ShaderNodeGroup", "mod_group"
    )
    mod_group.node_tree = mod_tree

    if not is_layer:
        # Create modifier group neighbor
        mod_n = new_node(parent_tree, parent, "mod_n", "ShaderNodeGroup", "mod_n")
        mod_s = new_node(parent_tree, parent, "mod_s", "ShaderNodeGroup", "mod_s")
        mod_e = new_node(parent_tree, parent, "mod_e", "ShaderNodeGroup", "mod_e")
        mod_w = new_node(parent_tree, parent, "mod_w", "ShaderNodeGroup", "mod_w")
        mod_n.node_tree = mod_tree
        mod_s.node_tree = mod_tree
        mod_e.node_tree = mod_tree
        mod_w.node_tree = mod_tree
    else:
        mod_group_1 = new_node(
            parent_tree, parent, "mod_group_1", "ShaderNodeGroup", "mod_group_1"
        )
        mod_group_1.node_tree = mod_tree

    for mod in parent.modifiers:
        check_modifier_nodes(mod, mod_tree, parent_tree)

    if rearrange:
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)


def disable_modifiers_tree(parent, parent_tree=None, rearrange=False):
    """Disable and remove the dedicated modifier tree for a parent layer or channel.

    Moves modifier nodes from the dedicated modifier tree back into the parent tree,
    then removes the modifier tree node group and associated neighbor nodes.

    Args:
        parent: The parent object (layer or channel) whose modifier tree will be disabled.
        parent_tree (optional): The parent ShaderNodeTree containing the modifier group.
            Defaults to None (auto-detected).
        rearrange (bool, optional): If True, reconnects and rearranges layer nodes
            after disabling the tree. Defaults to False.

    Returns:
        None
    """
    group_tree = parent.id_data
    mp = group_tree.mp

    if not parent_tree:

        match1 = re.match(
            r"^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$", parent.path_from_id()
        )
        match2 = re.match(r"^mp\.layers\[(\d+)\]$", parent.path_from_id())

        if match1:
            layer = mp.layers[int(match1.group(1))]
            root_ch = mp.channels[int(match1.group(2))]

            # Check if fine bump map is still used
            if (
                get_channel_enabled(parent, layer, root_ch)
                and len(parent.modifiers) > 0
                and root_ch.type == "NORMAL"
                and root_ch.enable_smooth_bump
            ):
                if (
                    layer.type not in {"BACKGROUND", "COLOR", "OBJECT_INDEX"}
                    and not parent.override
                ):
                    return
                if parent.override and parent.override_type != "DEFAULT":
                    return
            parent_tree = get_tree(layer)

        elif match2:
            layer = parent
            if layer.type in {
                "IMAGE",
                "VCOL",
                "BACKGROUND",
                "COLOR",
                "GROUP",
                "MUSGRAVE",
            }:
                return
            if layer.source_group != "":
                parent_tree = get_source_tree(layer)
            else:
                parent_tree = get_tree(layer)

        else:
            return

    if not parent_tree:
        return

    # Get modifier group
    mod_group = parent_tree.nodes.get(parent.mod_group)

    if mod_group:

        # Add new copied modifier nodes into the layer tree
        for mod in parent.modifiers:
            check_modifier_nodes(mod, parent_tree, mod_group.node_tree)

        # Remove modifier tree
        remove_node(parent_tree, parent, "mod_group")

        # Remove modifier group neighbor
        remove_node(parent_tree, parent, "mod_n")
        remove_node(parent_tree, parent, "mod_s")
        remove_node(parent_tree, parent, "mod_e")
        remove_node(parent_tree, parent, "mod_w")
        remove_node(parent_tree, parent, "mod_group_1")
