# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from mathutils import Vector

from ...utils.blender_commons import (
    get_bpy_data,
    get_current_blender_version_str,
    get_user_preferences,
    remove_datablock,
)
from ...utils.common import get_mix_color_indices, id_generator, set_mix_clamp
from ...utils.constants import (
    GEOMETRY,
    INFO_PREFIX,
    ONE_VALUE,
    TEXCOORD,
    TREE_END,
    TREE_START,
    MP_GROUP_PREFIX,
    ZERO_VALUE,
    limited_mask_blend_types,
    neighbor_directions,
)
from ..io.input_outputs.inputs import get_tree_inputs, new_tree_input
from ..io.input_outputs.outputs import new_tree_output
from ..lib.lib import SMOOTH_PREFIX
from .node_utils import create_info_nodes, get_node_tree_lib, remove_node, remove_tree_inside_tree


def create_essential_nodes(tree, solid_value=False, texcoord=False, geometry=False):
    """
    Create essential nodes for a node tree including input/output nodes and optional utility nodes.

    Parameters:
        tree: Node tree to add essential nodes to.
        solid_value (optional): If True, create ONE_VALUE and ZERO_VALUE nodes. Default: False.
        texcoord (optional): If True, create a TEXCOORD node. Default: False.
        geometry (optional): If True, create a GEOMETRY node. Default: False.

    Returns:
        None. Nodes are created directly in the tree.
    """

    # Start
    node = tree.nodes.new('NodeGroupInput')
    node.name = TREE_START
    node.label = 'Start'

    # End
    node = tree.nodes.new('NodeGroupOutput')
    node.name = TREE_END
    node.label = 'End'

    # Create solid value node
    if solid_value:
        node = tree.nodes.new('ShaderNodeValue')
        node.name = ONE_VALUE
        node.label = 'One Value'
        node.outputs[0].default_value = 1.0

        node = tree.nodes.new('ShaderNodeValue')
        node.name = ZERO_VALUE
        node.label = 'Zero Value'
        node.outputs[0].default_value = 0.0

    if geometry:
        node = tree.nodes.new('ShaderNodeNewGeometry')
        node.name = GEOMETRY

    if texcoord:
        node = tree.nodes.new('ShaderNodeTexCoord')
        node.name = TEXCOORD

def new_node(tree, entity, prop, node_id_name, label=''):
    """
    Create a new node and assign it to an entity's property.

    Parameters:
        tree: Node tree to add the new node to.
        entity: Entity object that will store the node reference.
        prop: Property name on entity to store the node's name.
        node_id_name: Blender node ID name (e.g., 'ShaderNodeMix').
        label (optional): Label to assign to the node. Default: ''.

    Returns:
        The newly created node, or None if entity doesn't have the specified property.
    """
    if not hasattr(entity, prop): return

    # Create new node
    node = tree.nodes.new(node_id_name)

    # Add random chars to make sure the node is unique
    node.name += ' ' + id_generator()

    # Set node name to object attribute
    setattr(entity, prop, node.name)

    # Set label
    node.label = label

    return node

def check_new_node(tree, entity, prop, node_id_name, label='', return_dirty=False):
    """
    Check if a node exists for an entity's property, create one if it doesn't exist.

    Parameters:
        tree: Node tree to search for or add the node to.
        entity: Entity object that stores the node reference.
        prop: Property name on entity that stores the node's name.
        node_id_name: Blender node ID name to use if creating a new node.
        label (optional): Label to assign to the node if created. Default: ''.
        return_dirty (optional): If True, return tuple (node, dirty_flag). Default: False.

    Returns:
        If return_dirty is False: The node (existing or newly created), or None if error.
        If return_dirty is True: Tuple of (node, dirty_flag) where dirty_flag is True if node was created.
    """

    dirty = False

    # Try to get the node first
    try:
        node = tree.nodes.get(getattr(entity, prop))
    except (AttributeError, TypeError, KeyError):
        if return_dirty:
            return None, dirty
        return None

    # Create new node if not found
    if not node:
        node = new_node(tree, entity, prop, node_id_name, label)
        dirty = True

    if return_dirty:
        return node, dirty

    return node


def new_mix_node(tree, entity, prop, label='', data_type='RGBA'):
    """
    Create a new ShaderNodeMix node and assign it to an entity's property.

    Parameters:
        tree: Node tree to add the new mix node to.
        entity: Entity object that will store the node reference.
        prop: Property name on entity to store the node's name.
        label (optional): Label to assign to the mix node. Default: ''.
        data_type (optional): Data type for the mix node (e.g., 'RGBA', 'FLOAT'). Default: 'RGBA'.

    Returns:
        The newly created mix node, or None if entity doesn't have the specified property.
    """
    if not hasattr(entity, prop): return

    node_id_name = 'ShaderNodeMix'

    node = new_node(tree, entity, prop, node_id_name, label)
    node.data_type = data_type

    return node

def simple_new_mix_node(tree, data_type='RGBA', label=''):
    """
    Create a simple mix node without entity association.

    Parameters:
        tree: Node tree to add the new mix node to.
        data_type (optional): Data type for the mix node (e.g., 'RGBA', 'FLOAT'). Default: 'RGBA'.
        label (optional): Label to assign to the mix node. Default: ''.

    Returns:
        The newly created mix node.
    """

    node = tree.nodes.new('ShaderNodeMix')
    node.data_type = data_type

    if label != '': node.label = label

    return node

def get_smooth_mix_node(blend_type, layer_type=''):
    """
    Get or create a smooth mix node group tree for a specific blend type and layer type.

    Parameters:
        blend_type: Blend type for the mix operation (e.g., 'MIX', 'MULTIPLY', 'ADD').
        layer_type (optional): Layer type, used to determine if group-specific version is needed. Default: ''.

    Returns:
        Node group tree configured for smooth mixing with the specified blend type.
    """

    is_group_limited = layer_type == 'GROUP' and blend_type in limited_mask_blend_types

    tree_name = SMOOTH_PREFIX + blend_type
    if is_group_limited:
        tree_name += ' Group'

    tree = get_bpy_data().node_groups.get(tree_name)

    if not tree:
        tree = get_bpy_data().node_groups.new(tree_name, 'ShaderNodeTree')

        # IO
        inp = new_tree_input(tree, 'Fac', 'NodeSocketFloatFactor')
        inp.min_value = 0.0
        inp.max_value = 1.0

        new_tree_input(tree, 'Color1', 'NodeSocketColor')
        for d in neighbor_directions:
            new_tree_input(tree, 'Color1 ' + d, 'NodeSocketColor')

        new_tree_input(tree, 'Color2', 'NodeSocketColor')
        for d in neighbor_directions:
            new_tree_input(tree, 'Color2 ' + d, 'NodeSocketColor')

        new_tree_output(tree, 'Color', 'NodeSocketColor')
        for d in neighbor_directions:
            new_tree_output(tree, 'Color ' + d, 'NodeSocketColor')

        # Group alpha limit inputs
        if is_group_limited:
            inp = new_tree_input(tree, 'Limit', 'NodeSocketFloat')
            inp.default_value = 1.0
            for d in neighbor_directions:
                inp = new_tree_input(tree, 'Limit ' + d, 'NodeSocketFloat')
                inp.default_value = 1.0

        # Nodes
        create_essential_nodes(tree)

        start = tree.nodes.get(TREE_START)
        end = tree.nodes.get(TREE_END)

        loc = Vector((0, 0))

        start.location = loc

        loc.x += 200
        bookmark_x = loc.x

        mix = simple_new_mix_node(tree)
        mixcol0, mixcol1, mixout = get_mix_color_indices(mix)
        mix.name = '_mix'
        mix.blend_type = blend_type
        if blend_type not in {'MIX', 'MULTIPLY'}: 
            set_mix_clamp(mix, True)

        mix.location = loc

        tree.links.new(start.outputs['Fac'], mix.inputs[0])
        tree.links.new(start.outputs['Color1'], mix.inputs[mixcol0])
        tree.links.new(start.outputs['Color2'], mix.inputs[mixcol1])
        if not is_group_limited:
            tree.links.new(mix.outputs[mixout], end.inputs['Color'])
        else:
            loc.x += 200

            limit = tree.nodes.new('ShaderNodeMath')
            limit.name = '_limit'
            limit.operation = 'MINIMUM'
            limit.use_clamp = True

            limit.location = loc

            tree.links.new(mix.outputs[mixout], limit.inputs[0])
            tree.links.new(start.outputs['Limit'], limit.inputs[1])
            tree.links.new(limit.outputs[0], end.inputs['Color'])

        loc.y -= 200

        for d in neighbor_directions:

            loc.x = bookmark_x

            mix = simple_new_mix_node(tree)
            mixcol0, mixcol1, mixout = get_mix_color_indices(mix)
            mix.name = '_mix_' + d
            mix.blend_type = blend_type
            if blend_type not in {'MIX', 'MULTIPLY'}: 
                set_mix_clamp(mix, True)

            mix.location = loc

            tree.links.new(start.outputs['Fac'], mix.inputs[0])
            tree.links.new(start.outputs['Color1 ' + d], mix.inputs[mixcol0])
            tree.links.new(start.outputs['Color2 ' + d], mix.inputs[mixcol1])

            if not is_group_limited:
                tree.links.new(mix.outputs[mixout], end.inputs['Color ' + d])
            else:
                loc.x += 200

                limit = tree.nodes.new('ShaderNodeMath')
                limit.name = '_limit_' + d
                limit.operation = 'MINIMUM'
                limit.use_clamp = True

                limit.location = loc

                tree.links.new(mix.outputs[mixout], limit.inputs[0])
                tree.links.new(start.outputs['Limit ' + d], limit.inputs[1])
                tree.links.new(limit.outputs[0], end.inputs['Color ' + d])

            loc.y -= 200

        loc.x += 200

        end.location.x = loc.x

    return tree

def create_new_group_tree(mat, name=None):
    """
    Create a new mpaint group node tree for a material.

    Parameters:
        mat: Material object to create the group tree for.
        name (optional): Name for the group tree. If None, uses MP_GROUP_PREFIX + material name. Default: None.

    Returns:
        The newly created group tree configured as a mpaint node with essential nodes and info nodes.
    """

    #mpup = bpy.context.user_preferences.addons[__name__].preferences

    # Group name is based on material unless specified
    group_name = name or MP_GROUP_PREFIX + mat.name

    # Create new group tree
    group_tree = get_bpy_data().node_groups.new(group_name, 'ShaderNodeTree')
    group_tree.mp.is_mpaint_node = True
    group_tree.mp.blender_version = get_current_blender_version_str()
    group_tree.mp.enable_baked_outside = get_user_preferences().enable_baked_outside_by_default

    # Create IO nodes
    create_essential_nodes(group_tree, True, True, True)

    # Create info nodes
    create_info_nodes(group_tree)

    return group_tree

def replace_new_node(tree, entity, prop, node_id_name, label='', group_name='', return_status=False, hard_replace=False, dirty=False, force_replace=False):
    """
    Check if a node exists, replace it if needed with a new node or update group tree.

    Parameters:
        tree: Node tree to search for or add the node to.
        entity: Entity object that stores the node reference.
        prop: Property name on entity that stores the node's name.
        node_id_name: Blender node ID name to use for the node.
        label (optional): Label to assign to the node. Default: ''.
        group_name (optional): Name of group tree to use for GROUP nodes. Default: ''.
        return_status (optional): If True, return tuple (node, dirty_flag). Default: False.
        hard_replace (optional): If True, completely remove and recreate the node. Default: False.
        dirty (optional): Initial dirty state. Default: False.
        force_replace (optional): If True, force replacement of group tree. Default: False.

    Returns:
        If return_status is False: The node (existing, replaced, or newly created).
        If return_status is True: Tuple of (node, dirty_flag) where dirty_flag indicates if changes were made.
    """

    # Try to get the node first
    try:
        node = tree.nodes.get(getattr(entity, prop))
    except (AttributeError, TypeError, KeyError):
        return None, False

    #dirty = False

    # Remove node if found and has different id name
    if node and node.bl_idname != node_id_name:
        remove_node(tree, entity, prop)
        node = None
        dirty = True

    # Create new node
    if not node:
        node = new_node(tree, entity, prop, node_id_name, label)
        dirty = True

    if node.type == 'GROUP':

        # Get previous tree
        prev_tree = node.node_tree

        # Check if group is copied
        if prev_tree:
            m = re.match(r'^' + group_name + '_Copy\.*\d{0,3}$', prev_tree.name)
        else: m = None

        #print(prev_tree)

        if not prev_tree or force_replace or (prev_tree.name != group_name and not m):

            if hard_replace or force_replace:
                tree.nodes.remove(node)
                node = new_node(tree, entity, prop, node_id_name, label)
                dirty = True

            # Replace group tree
            node.node_tree = get_node_tree_lib(group_name)

            if not prev_tree:
                dirty = True

            else:
                # Compare previous group inputs with current group inputs
                if len(get_tree_inputs(prev_tree)) != len(node.inputs):
                    dirty = True
                else:
                    for i, inp in enumerate(node.inputs):
                        if inp.name != get_tree_inputs(prev_tree)[i].name:
                            dirty = True
                            break

                # Remove previous tree if it has no user
                if prev_tree.users == 0:
                    remove_tree_inside_tree(prev_tree)
                    remove_datablock(get_bpy_data().node_groups, prev_tree)

    if return_status:
        return node, dirty
    return node

def check_new_mix_node(tree, entity, prop, label='', return_dirty=False, data_type='RGBA'):
    """
    Check if a mix node exists for an entity's property, create one if it doesn't exist.

    Parameters:
        tree: Node tree to search for or add the mix node to.
        entity: Entity object that stores the node reference.
        prop: Property name on entity that stores the node's name.
        label (optional): Label to assign to the mix node if created. Default: ''.
        return_dirty (optional): If True, return tuple (node, dirty_flag). Default: False.
        data_type (optional): Data type for the mix node if created. Default: 'RGBA'.

    Returns:
        If return_dirty is False: The mix node (existing or newly created), or None if error.
        If return_dirty is True: Tuple of (node, dirty_flag) where dirty_flag is True if node was created.
    """

    dirty = False

    # Try to get the node first
    try:
        node = tree.nodes.get(getattr(entity, prop))
    except (AttributeError, TypeError, KeyError):
        if return_dirty:
            return None, dirty
        return None

    # Create new node if not found
    if not node:
        node = new_mix_node(tree, entity, prop, label, data_type)
        dirty = True

    if return_dirty:
        return node, dirty

    return node
