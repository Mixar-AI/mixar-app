# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

import bpy

from ...core.io.input_outputs.inputs import new_tree_input
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.io.input_outputs.outputs import new_tree_output
from ...core.layer.check_layers import get_channel_enabled
from ...core.modifier.modifier_commons import check_modifier_nodes
from ...core.node.create_nodes import new_node
from ...core.node.node_utils import remove_node
from ...core.subtree.get_subtree import get_mod_tree, get_source_tree, get_tree
from ...utils.constants import MOD_TREE_END, MOD_TREE_START


def get_modifier_channel_type(mod, return_non_color=False):
    """Get the channel type for a modifier based on its location in the hierarchy.

    Args:
        mod: The modifier object to analyze.
        return_non_color (bool): If True, return both channel_type and non_color flag. Defaults to False.

    Returns:
        str or tuple: If return_non_color is False, returns channel_type string (e.g., "RGB", "NORMAL").
            If return_non_color is True, returns tuple of (channel_type, non_color).
    """
    mp = mod.id_data.mp
    match1 = re.match(
        r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers\[(\d+)\]",
        mod.path_from_id(),
    )
    match2 = re.match(r"mp\.channels\[(\d+)\]\.modifiers\[(\d+)\]", mod.path_from_id())
    match3 = re.match(r"mp\.layers\[(\d+)\]\.modifiers\[(\d+)\]", mod.path_from_id())
    if match1:
        root_ch = mp.channels[int(match1.group(2))]

        # Get non color flag and channel type
        non_color = root_ch.colorspace == "LINEAR" or root_ch.type == "VALUE"
        channel_type = root_ch.type
    elif match2:
        root_ch = mp.channels[int(match2.group(1))]

        # Get non color flag and channel type
        non_color = root_ch.colorspace == "LINEAR" or root_ch.type == "VALUE"
        channel_type = root_ch.type
    elif match3:

        # Image layer modifiers always use srgb colorspace
        layer = mp.layers[int(match3.group(1))]
        non_color = layer.type != "IMAGE"
        channel_type = "RGB"

    if return_non_color:
        return channel_type, non_color

    return channel_type


def update_modifier_enable(self, context):
    """Update callback when a modifier's enable state changes.

    Args:
        self: The modifier property that was updated.
        context: Blender context object.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    tree = get_mod_tree(self)

    check_modifier_nodes(self, tree)

    match1 = re.match(
        r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers\[(\d+)\]",
        self.path_from_id(),
    )
    match2 = re.match(r"mp\.layers\[(\d+)\]\.modifiers\[(\d+)\]", self.path_from_id())
    match3 = re.match(r"mp\.channels\[(\d+)\]\.modifiers\[(\d+)\]", self.path_from_id())

    if match1 or match2:
        if match1:
            layer = mp.layers[int(match1.group(1))]
        else:
            layer = mp.layers[int(match2.group(1))]

        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

    elif match3:
        channel = mp.channels[int(match3.group(1))]
        reconnect_mp_nodes(self.id_data)
        rearrange_mp_nodes(self.id_data)


def enable_modifiers_tree(
    parent, parent_tree=None, name="", is_layer=False, rearrange=False
):
    """Enable and create modifier tree for a parent (layer or channel).

    Args:
        parent: The parent object (layer or channel) to enable modifiers for.
        parent_tree: The parent node tree. Defaults to None (will be determined from parent).
        name (str): Name for the modifier tree. Defaults to "" (will be generated).
        is_layer (bool): Whether the parent is a layer. Defaults to False.
        rearrange (bool): Whether to rearrange nodes after enabling. Defaults to False.

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
    mod_tree = bpy.data.node_groups.new("~yP Modifiers " + name, "ShaderNodeTree")

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
    """Disable and remove modifier tree for a parent (layer or channel).

    Args:
        parent: The parent object (layer or channel) to disable modifiers for.
        parent_tree: The parent node tree. Defaults to None (will be determined from parent).
        rearrange (bool): Whether to rearrange nodes after disabling. Defaults to False.

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
