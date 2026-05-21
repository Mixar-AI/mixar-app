# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...utils.blender_commons import get_bpy_data
from ...utils.constants import MASKGROUP_PREFIX
from ..io.input_outputs.inputs import new_tree_input
from ..io.arrangements.layer_arrangements import rearrange_layer_nodes
from ..io.connections.layer_connections import reconnect_layer_nodes
from ..io.input_outputs.outputs import new_tree_output
from ..modifier.mask_modifier import add_modifier_nodes
from ..node.create_nodes import create_essential_nodes, new_node
from ..node.node_utils import copy_node_props, remove_node
from ..subtree.get_subtree import get_mask_tree, get_tree


def set_parent_dict_val(mp, parent_dict, name, target_idx):
    """Set or update a parent relationship in the parent dictionary.

    Args:
        mp: The MPaint data structure containing layer information.
        parent_dict (dict): Dictionary mapping layer names to their parent layer names.
        name (str): The name of the layer to set the parent for.
        target_idx (int): Index of the parent layer. If -1, sets parent to None.

    Returns:
        dict: Updated parent_dict with the new or modified parent relationship.
    """
    if target_idx != -1:
        parent_dict[name] = mp.layers[target_idx].name
    else: parent_dict[name] = None

    return parent_dict

def enable_mask_source_tree(layer, mask, reconnect = False):
    """Enable and create a mask source tree for a layer mask.

    Creates a node group for the mask source, copies source nodes from references,
    and sets up the mask tree structure with inputs, outputs, and essential nodes.

    Args:
        layer: The layer object containing the mask.
        mask: The mask object to enable source tree for.
        reconnect (bool, optional): If True, reconnects and rearranges layer nodes
            after enabling the source tree. Defaults to False.

    Returns:
        None
    """
    # Check if source tree is already available
    #if (mask.use_baked or mask.type not in {'VCOL', 'HEMI', 'OBJECT_INDEX', 'COLOR_ID', 'BACKFACE', 'EDGE_DETECT'}) and mask.group_node != '': return

    layer_tree = get_tree(layer)

    # Create uv neighbor
    #check_mask_uv_neighbor(layer_tree, layer, mask)

    if mask.group_node == '' and (mask.use_baked or mask.type not in {'VCOL', 'HEMI', 'OBJECT_INDEX', 'COLOR_ID', 'BACKFACE', 'EDGE_DETECT'}):
        # Get current source for reference
        source_ref = layer_tree.nodes.get(mask.source)
        baked_source_ref = layer_tree.nodes.get(mask.baked_source)
        linear_ref = layer_tree.nodes.get(mask.linear)

        # Create mask tree
        mask_tree = get_bpy_data().node_groups.new(MASKGROUP_PREFIX + mask.name, 'ShaderNodeTree')

        # Create input and outputs
        if mask.type == 'MODIFIER':
            new_tree_input(mask_tree, 'Value', 'NodeSocketFloat')
        else: new_tree_input(mask_tree, 'Vector', 'NodeSocketVector')
        new_tree_output(mask_tree, 'Value', 'NodeSocketFloat')

        create_essential_nodes(mask_tree)

        # Copy nodes from reference
        source = new_node(mask_tree, mask, 'source', source_ref.bl_idname)
        copy_node_props(source_ref, source)
        if baked_source_ref:
            baked_source = new_node(mask_tree, mask, 'baked_source', baked_source_ref.bl_idname)
            copy_node_props(baked_source_ref, baked_source)

        if linear_ref:
            linear = new_node(mask_tree, mask, 'linear', linear_ref.bl_idname)
            copy_node_props(linear_ref, linear)

        # Create source node group
        group_node = new_node(layer_tree, mask, 'group_node', 'ShaderNodeGroup', 'source_group')
        source_n = new_node(layer_tree, mask, 'source_n', 'ShaderNodeGroup', 'source_n')
        source_s = new_node(layer_tree, mask, 'source_s', 'ShaderNodeGroup', 'source_s')
        source_e = new_node(layer_tree, mask, 'source_e', 'ShaderNodeGroup', 'source_e')
        source_w = new_node(layer_tree, mask, 'source_w', 'ShaderNodeGroup', 'source_w')

        group_node.node_tree = mask_tree
        source_n.node_tree = mask_tree
        source_s.node_tree = mask_tree
        source_e.node_tree = mask_tree
        source_w.node_tree = mask_tree

        for mod in mask.modifiers:
            add_modifier_nodes(mod, mask_tree, layer_tree)

        # Remove previous nodes
        layer_tree.nodes.remove(source_ref)
        if baked_source_ref: layer_tree.nodes.remove(baked_source_ref)
        if linear_ref: layer_tree.nodes.remove(linear_ref)

    if reconnect:
        # Reconnect outside nodes
        reconnect_layer_nodes(layer)

        # Rearrange nodes
        rearrange_layer_nodes(layer)

def disable_mask_source_tree(layer, mask, reconnect=False):
    """Disable and remove the mask source tree, restoring nodes to the layer tree.

    Converts mask source nodes back from the mask tree group to individual nodes
    in the layer tree, and cleans up all associated group nodes.

    Args:
        layer: The layer object containing the mask.
        mask: The mask object to disable source tree for.
        reconnect (bool, optional): If True, reconnects and rearranges layer nodes
            after disabling the source tree. Defaults to False.

    Returns:
        None
    """
    # Check if source tree is already gone
    #if mask.type not in {'VCOL', 'HEMI', 'OBJECT_INDEX', 'COLOR_ID', 'BACKFACE'} and mask.group_node == '': return

    layer_tree = get_tree(layer)

    if mask.group_node != '': #and (mask.use_baked or mask.type not in {'VCOL', 'HEMI', 'OBJECT_INDEX', 'COLOR_ID', 'BACKFACE'}):

        mask_tree = get_mask_tree(mask)

        source_ref = mask_tree.nodes.get(mask.source)
        baked_source_ref = mask_tree.nodes.get(mask.baked_source)
        linear_ref = mask_tree.nodes.get(mask.linear)
        group_node = layer_tree.nodes.get(mask.group_node)

        # Create new nodes
        source = new_node(layer_tree, mask, 'source', source_ref.bl_idname)
        copy_node_props(source_ref, source)

        if baked_source_ref:
            baked_source = new_node(layer_tree, mask, 'baked_source', baked_source_ref.bl_idname)
            copy_node_props(baked_source_ref, baked_source)

        if linear_ref:
            linear = new_node(layer_tree, mask, 'linear', linear_ref.bl_idname)
            copy_node_props(linear_ref, linear)

        for mod in mask.modifiers:
            add_modifier_nodes(mod, layer_tree, mask_tree)

        # Remove previous source
        remove_node(layer_tree, mask, 'group_node')
        remove_node(layer_tree, mask, 'source_n')
        remove_node(layer_tree, mask, 'source_s')
        remove_node(layer_tree, mask, 'source_e')
        remove_node(layer_tree, mask, 'source_w')
        remove_node(layer_tree, mask, 'tangent')
        remove_node(layer_tree, mask, 'bitangent')
        remove_node(layer_tree, mask, 'tangent_flip')
        remove_node(layer_tree, mask, 'bitangent_flip')

    #remove_node(layer_tree, mask, 'uv_neighbor')

    if reconnect:
        # Reconnect outside nodes
        reconnect_layer_nodes(layer)

        # Rearrange nodes
        rearrange_layer_nodes(layer)

def move_mod_group(layer, from_tree, to_tree):
    """Move a modifier group node from one tree to another.

    Transfers the modifier group and its duplicate from the source tree to the
    destination tree while preserving the node tree reference.

    Args:
        layer: The layer object containing the modifier group reference.
        from_tree: The source node tree containing the modifier group.
        to_tree: The destination node tree to move the modifier group to.

    Returns:
        None
    """
    mod_group = from_tree.nodes.get(layer.mod_group)
    if mod_group:
        mod_tree = mod_group.node_tree
        remove_node(from_tree, layer, 'mod_group', remove_data=False)
        remove_node(from_tree, layer, 'mod_group_1', remove_data=False)

        mod_group = new_node(to_tree, layer, 'mod_group', 'ShaderNodeGroup', 'mod_group')
        mod_group.node_tree = mod_tree
        mod_group_1 = new_node(to_tree, layer, 'mod_group_1', 'ShaderNodeGroup', 'mod_group_1')
        mod_group_1.node_tree = mod_tree
