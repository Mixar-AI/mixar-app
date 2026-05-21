# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Node tree management utilities.

This module contains functions for managing node trees, including
tree library operations, node removal, and essential node management.
"""

import re

from mathutils import Vector

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...utils.blender_commons import (
    get_active_material,
    get_bpy_context,
    get_bpy_data,
    remove_datablock,
    safe_remove_image,
)
from ...utils.common import get_vcol_bl_idname
from ...utils.constants import (
    GEOMETRY,
    INFO_PREFIX,
    ONE_VALUE,
    TEXCOORD,
    TREE_END,
    TREE_START,
    ZERO_VALUE,
)
from ..lib.lib import DECAL_PROCESS
from ..lib.lib_operations import load_from_lib_blend
from ..material.get_materials import get_all_objects_with_same_materials


def is_vcol_being_used(tree, vcol_name, exception_node=None):
    """Check if a vertex color is being used in a node tree.

    Recursively searches through a node tree to determine if a vertex color
    (identified by name) is being used by any VERTEX_COLOR or ATTRIBUTE nodes,
    or within any GROUP nodes.

    Args:
        tree: The Blender node tree to search.
        vcol_name (str): The name of the vertex color to search for.
        exception_node: A node to exclude from the search (default: None).

    Returns:
        bool: True if the vertex color is being used, False otherwise.
    """
    for node in tree.nodes:
        if node.type == 'VERTEX_COLOR' and node.layer_name == vcol_name and node != exception_node:
            return True
        elif node.type == 'ATTRIBUTE' and node.attribute_name == vcol_name and node != exception_node:
            return True
        elif node.type == 'GROUP' and is_vcol_being_used(node.node_tree, vcol_name, exception_node):
            return True

    return False


def create_info_nodes(tree):
    """Create informational warning nodes in a MPaint node tree.

    Creates a warning frame node that displays a message to users not to manually
    edit the group. The position and location of the info node varies based on
    the tree type (ROOT, LAYER, or LIB).

    Args:
        tree: The MPaint node tree where info nodes will be created.
    """
    mp = tree.mp
    nodes = tree.nodes

    if mp.is_mpaint_node:
        tree_type = 'ROOT'
    elif mp.is_mpaint_layer_node:
        tree_type = 'LAYER'
    else: tree_type = 'LIB'

    # Delete previous info nodes
    for node in nodes:
        if node.name.startswith(INFO_PREFIX):
            nodes.remove(node)

    # Create info nodes
    infos = []

    info = nodes.new('NodeFrame')
    info.label = 'WARNING: Do NOT edit this group manually!'
    info.use_custom_color = True
    info.color = (1.0, 0.5, 0.5)
    info.width = 450.0
    info.height = 60.0
    infos.append(info)

    if tree_type in {'LAYER', 'ROOT'}:

        loc = Vector((0, 70))

        for info in reversed(infos):
            info.name = INFO_PREFIX + info.name

            loc.y += 80
            info.location = loc
    else:

        # Get group input node
        try:
            inp = [n for n in nodes if n.type == 'GROUP_INPUT'][0]
            loc = Vector((inp.location[0] - 620, inp.location[1]))
        except: loc = Vector((-620, 0))

        for info in infos:
            info.name = INFO_PREFIX + info.name

            loc.y -= 80
            info.location = loc


def check_duplicated_node_group(node_group, duplicated_trees=[]):
    """Check for and fix duplicated node groups in a tree.

    Recursively traverses a node group to find duplicated node trees (identified by
    .001, .002, etc. suffixes) and replaces them with the original node tree. Also
    creates info frames if they are missing from MPaint layer nodes.

    Args:
        node_group: The Blender node group to check.
        duplicated_trees (list): A list to accumulate duplicated trees found (default: []).
    """

    info_frame_found = False

    for node in node_group.nodes:

        # Check if info frame is found in this tree
        if node.type == 'FRAME' and node.name.startswith(INFO_PREFIX):
            info_frame_found = True

        if node.type == 'GROUP' and node.node_tree:

            # Check if its node tree duplicated
            m = re.match(r'^(.+)\.\d{3}$', node.node_tree.name)
            if m:
                ng = get_bpy_data().node_groups.get(m.group(1))
                if ng:

                    # Remember current tree
                    prev_tree = node.node_tree

                    # HACK: Remember links because sometime tree sockets are unlinked
                    from_nodes = []
                    from_sockets = []
                    to_sockets = []
                    for inp in node.inputs:
                        for l in inp.links:
                            from_nodes.append(l.from_node.name)
                            socket_index = [i for i, soc in enumerate(l.from_node.outputs) if soc == l.from_socket][0]
                            from_sockets.append(socket_index)
                            to_sockets.append(inp.name)

                    # Replace new node
                    node.node_tree = ng

                    # HACK: Recover the unlinkeds
                    for i, inp_name in enumerate(to_sockets):
                        inp = node.inputs.get(inp_name)
                        if not inp: continue
                        from_node = node_group.nodes.get(from_nodes[i])
                        if len(inp.links) == 0:
                            try: node_group.links.new(from_node.outputs[from_sockets[i]], inp)
                            except Exception as e: logger.error(e)

                    if prev_tree not in duplicated_trees:
                        duplicated_trees.append(prev_tree)

            check_duplicated_node_group(node.node_tree, duplicated_trees)

    # Create info frame if not found
    if not info_frame_found and node_group.name.startswith('~yPL '):
        create_info_nodes(node_group)


def get_node_tree_lib(name):
    """Get a node tree from the library, loading it if necessary.

    First attempts to get the node tree from local Blender data. If not found,
    loads it from the library blend file. For certain node groups (like Decal Process),
    if still not found, creates them programmatically. Also checks for and removes
    any duplicated node groups within the loaded tree.

    Args:
        name (str): The name of the node tree to retrieve.

    Returns:
        The node tree object if found/loaded/created, None otherwise.
    """

    # Try to get from local lib first
    node_tree = get_bpy_data().node_groups.get(name)
    if node_tree:
        return node_tree

    # Load from library blend file
    load_from_lib_blend(name, 'lib.blend')

    node_tree = get_bpy_data().node_groups.get(name)

    # If still not found, try to create programmatically for supported node groups
    if not node_tree:
        node_tree = _create_node_tree_programmatically(name)

    # Check if another group is exists inside the group
    if node_tree:
        duplicated_trees = []
        check_duplicated_node_group(node_tree, duplicated_trees)

        # Remove duplicated trees
        for t in duplicated_trees:
            remove_datablock(get_bpy_data().node_groups, t)

    return node_tree


def _create_node_tree_programmatically(name):
    """Create a node tree programmatically if it's a supported type.

    Some node groups can be created on-the-fly if they're not in the library.
    This provides a fallback mechanism for missing library assets.

    Args:
        name (str): The name of the node tree to create.

    Returns:
        The created node tree, or None if not supported.
    """
    if name == DECAL_PROCESS:
        from ..lib.decal_nodegroup import get_decal_process_node_tree
        return get_decal_process_node_tree()

    return None


def remove_tree_inside_tree(tree):
    """Recursively remove node trees from GROUP nodes within a tree.

    Traverses all GROUP nodes in the tree and removes their node trees if they
    have only one user. Recursively processes nested group nodes.

    Args:
        tree: The Blender node tree to process.
    """
    for node in tree.nodes:
        if node.type == 'GROUP':
            if node.node_tree and node.node_tree.users == 1:
                remove_tree_inside_tree(node.node_tree)
                remove_datablock(get_bpy_data().node_groups, node.node_tree, user=node, user_prop='node_tree')
            else: node.node_tree = None


def get_vertex_colors(obj):
    """Get the color attributes (vertex colors) from a mesh object.

    Args:
        obj: The Blender object to get vertex colors from.

    Returns:
        The color_attributes collection if the object is a mesh, empty list otherwise.
    """
    if not obj or obj.type != 'MESH': return []
    return obj.data.color_attributes


def get_source_vcol_name(src):
    """Get the vertex color name from a source node.

    Args:
        src: The source node containing an attribute_name property.

    Returns:
        str: The attribute name from the source node.
    """
    return src.attribute_name


def remove_node(tree, entity, prop, remove_data=True, parent=None, remove_on_disk=False):
    """Remove a node from a tree and optionally clean up its associated data.

    Removes a node identified by a property name on an entity. Can optionally remove
    associated data such as images, node trees, and vertex colors. Handles special
    cases for texture images, group nodes, and vertex color nodes.

    Args:
        tree: The Blender node tree containing the node.
        entity: The entity object that has a property referencing the node.
        prop (str): The property name on the entity that contains the node name.
        remove_data (bool): Whether to remove associated data (default: True).
        parent: Optional parent node for validation (default: None).
        remove_on_disk (bool): Whether to remove image files from disk (default: False).

    Returns:
        bool: True if the tree was modified (dirty), False otherwise.
    """

    dirty = False

    if not hasattr(entity, prop): return dirty
    if not tree: return dirty
    #if prop not in entity: return dirty

    scene = get_bpy_context().scene
    node = tree.nodes.get(getattr(entity, prop))
    #node = tree.nodes.get(entity[prop])

    if node:

        dirty = True

        mp_tree = entity.id_data

        if parent and node.parent != parent:
            setattr(entity, prop, '')
            return dirty

        if remove_data:
            # Remove image data if the node is the only user
            if node.bl_idname == 'ShaderNodeTexImage':

                image = node.image
                if image: safe_remove_image(image, remove_on_disk, user=node, user_prop='image')

            elif node.bl_idname == 'ShaderNodeGroup':

                if node.node_tree and node.node_tree.users == 1:
                    remove_tree_inside_tree(node.node_tree)
                    remove_datablock(get_bpy_data().node_groups, node.node_tree, user=node, user_prop='node_tree')

            elif hasattr(entity, 'type') and entity.type == 'VCOL' and node.bl_idname == get_vcol_bl_idname():

                mat = get_active_material()
                objs = get_all_objects_with_same_materials(mat)

                for obj in objs:
                    if obj.type != 'MESH': continue

                    mat = obj.active_material
                    vcol_name = get_source_vcol_name(node)
                    vcols = get_vertex_colors(obj)
                    vcol = vcols.get(vcol_name)

                    if vcol:

                        # Check if vcol is being used somewhere else
                        obs = get_all_objects_with_same_materials(mat, True)
                        for o in obs:
                            other_users_found = False
                            for m in o.data.materials:
                                if m and m.node_tree and is_vcol_being_used(m.node_tree, vcol_name, node):
                                    other_users_found = True
                                    break
                            if not other_users_found:
                                vc = vcols.get(vcol_name)
                                if vc: vcols.remove(vc)

        tree.nodes.remove(node)
        dirty = True

    if getattr(entity, prop) != '':
        setattr(entity, prop, '')

    return dirty


def get_essential_node(tree, name):
    """Get or create an essential node in a tree.

    Retrieves an essential node by name, creating it if it doesn't exist. Essential
    nodes include TREE_START, TREE_END, ONE_VALUE, ZERO_VALUE, GEOMETRY, and TEXCOORD.

    Args:
        tree: The Blender node tree to search/modify.
        name (str): The name of the essential node (e.g., TREE_START, ONE_VALUE).

    Returns:
        The outputs of the node (or inputs if TREE_END).
    """
    node = tree.nodes.get(name)
    if not node:
        if name == TREE_START:
            node = tree.nodes.new('NodeGroupInput')
            node.name = TREE_START
            node.label = 'Start'

        elif name == TREE_END:
            node = tree.nodes.new('NodeGroupOutput')
            node.name = TREE_END
            node.label = 'End'

        elif name == ONE_VALUE:
            node = tree.nodes.new('ShaderNodeValue')
            node.name = ONE_VALUE
            node.label = 'One Value'
            node.outputs[0].default_value = 1.0

        elif name == ZERO_VALUE:
            node = tree.nodes.new('ShaderNodeValue')
            node.name = ZERO_VALUE
            node.label = 'Zero Value'
            node.outputs[0].default_value = 0.0

        elif name == GEOMETRY:
            node = tree.nodes.new('ShaderNodeNewGeometry')
            node.name = GEOMETRY

        elif name == TEXCOORD:
            node = tree.nodes.new('ShaderNodeTexCoord')
            node.name = TEXCOORD

    if name == TREE_END:
        return node.inputs

    return node.outputs


def clean_essential_nodes(tree, exclude_texcoord=False, exclude_geometry=False):
    """Check for all essential nodes and delete them if no links found.

    Removes essential nodes (ONE_VALUE, ZERO_VALUE, GEOMETRY, TEXCOORD, TREE_START,
    TREE_END) from the tree if they have no active connections.

    Args:
        tree: The Blender node tree to clean.
        exclude_texcoord (bool): Whether to exclude TEXCOORD from cleaning (default: False).
        exclude_geometry (bool): Whether to exclude GEOMETRY from cleaning (default: False).
    """
    for name in [ONE_VALUE, ZERO_VALUE, GEOMETRY, TEXCOORD, TREE_START, TREE_END]:
        if exclude_texcoord and name == TEXCOORD: continue
        if exclude_geometry and name == GEOMETRY: continue
        node = tree.nodes.get(name)
        if node:
            link_found = False
            if len(node.outputs) > 0:
                for outp in node.outputs:
                    if len(outp.links) > 0:
                        link_found = True
                        break
            elif len(node.inputs) > 0:
                for inp in node.inputs:
                    if len(inp.links) > 0:
                        link_found = True
                        break
            if not link_found:
                tree.nodes.remove(node)
