# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Active node utilities.

This module contains functions for getting and managing active nodes,
including MPaint nodes, normal channel inputs, and decal operations.
"""

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_bpy_context,
    get_bpy_data,
    get_unique_name,
    link_object,
)
from ...utils.constants import io_suffix


def get_node_input_index(node, inp):
    """Get the index of a specific input socket in a node.

    Args:
        node: The Blender node to search.
        inp: The input socket to find.

    Returns:
        int: The index of the input socket if found, -1 otherwise.
    """
    index = -1

    try: index = [i for i, s in enumerate(node.inputs) if s == inp][0]
    except Exception as e: logger.error("Error getting node input index: %s", e)

    return index


def get_active_node():
    """Get the active node from the active material's node tree.

    Returns:
        The active node if found, None otherwise.
    """
    mat = get_active_material()
    if not mat or not mat.node_tree: return None
    node = mat.node_tree.nodes.active
    return node


def get_active_mpaint_node(obj=None):
    """Get the active MPaint node from the active material.

    Retrieves the active MPaint node, managing the material UI properties and
    ensuring the correct node is tracked. Creates new material UI entries if needed
    and handles material name changes.

    Args:
        obj: Optional object to get the material from (default: None, uses active object).

    Returns:
        The active MPaint group node if found, None otherwise.
    """
    wm = get_bpy_context().window_manager
    if not hasattr(wm, 'mpui'):
        logger.debug("mpui not yet registered, returning None")
        return None
    mpui = wm.mpui

    # Get material UI prop
    mat = get_active_material(obj)
    if not mat or not mat.node_tree:
        mpui.active_mat = ''
        logger.debug(f"[get_active_mpaint_node] No material or node tree. mat={mat}, has_node_tree={mat.node_tree if mat else None}")
        return None

    # Search for its name first
    mui = mpui.materials.get(mat.name)

    # Flag for indicate new mui just created
    change_name = False

    # If still not found, create one
    if not mui:

        if mpui.active_mat != '':
            prev_mat = get_bpy_data().materials.get(mpui.active_mat)
            if not prev_mat:
                #print(mpui.active_mat)
                change_name = True
                # Remove prev mui
                prev_idx = [i for i, m in enumerate(mpui.materials) if m.name == mpui.active_mat]
                if prev_idx:
                    mpui.materials.remove(prev_idx[0])
                    #print('Removed!')

        mui = mpui.materials.add()
        mui.name = mat.name
        #print('New MUI!', mui.name)

    if mpui.active_mat != mat.name:
        mpui.active_mat = mat.name

    # Try to get mp node
    node = get_active_node()

    if node and node.type == 'GROUP' and node.node_tree and node.node_tree.mp.is_mpaint_node:
        # Update node name
        if mui.active_mpaint_node != node.name:
            #print('From:', mui.active_mpaint_node)
            mui.active_mpaint_node = node.name
            #print('To:', node.name)
        if mpui.active_mpaint_node != node.name:
            mpui.active_mpaint_node = node.name
        return node

    # If not active node isn't a group node
    # New mui possibly means material name just changed, try to get previous active node
    if change_name:
        node = mat.node_tree.nodes.get(mpui.active_mpaint_node)
        if node:
            #print(mui.name, 'Change name from:', mui.active_mpaint_node)
            mui.active_mpaint_node = node.name
            #print(mui.name, 'Change name to', mui.active_mpaint_node)
            return node

    node = mat.node_tree.nodes.get(mui.active_mpaint_node)
    if node and hasattr(node, 'node_tree') and node.node_tree and node.node_tree.mp.is_mpaint_node:
        return node

    # If node still not found
    for node in mat.node_tree.nodes:
        if node.type == 'GROUP' and node.node_tree and node.node_tree.mp.is_mpaint_node:
            #print('Last resort!', mui.name, mui.active_mpaint_node)
            mui.active_mpaint_node = node.name
            return node

    return None


def is_normal_vdisp_input_connected(root_normal_ch):
    """Check if the vertex displacement input is connected for a normal channel.

    Args:
        root_normal_ch: The root normal channel to check.

    Returns:
        bool: True if the vertex displacement input is connected, False otherwise.
    """
    # NOTE: Assuming that the active node is using the input tree
    node = get_active_mpaint_node()
    if not node: return False

    io_vdisp_name = root_normal_ch.name + io_suffix['VDISP']
    vdisp_inp = node.inputs.get(io_vdisp_name)
    return vdisp_inp and len(vdisp_inp.links) > 0


def is_normal_height_input_connected(root_normal_ch):
    """Check if the height input is connected for a normal channel.

    Args:
        root_normal_ch: The root normal channel to check.

    Returns:
        bool: True if the height input is connected, False otherwise.
    """
    # NOTE: Assuming that the active node is using the input tree
    node = get_active_mpaint_node()
    if not node: return False

    io_height_name = root_normal_ch.name + io_suffix['HEIGHT']
    height_inp = node.inputs.get(io_height_name)
    return height_inp and len(height_inp.links) > 0


def is_normal_input_connected(root_normal_ch):
    """Check if the normal input is connected for a normal channel.

    Args:
        root_normal_ch: The root normal channel to check.

    Returns:
        bool: True if the normal input is connected, False otherwise.
    """
    # NOTE: Assuming that the active node is using the input tree
    node = get_active_mpaint_node()
    if not node: return False

    normal_inp = node.inputs.get(root_normal_ch.name)
    return normal_inp and len(normal_inp.links) > 0


def create_decal_empty():
    """Create an empty object for decal placement.

    Creates a new empty object at the 3D cursor location, parented to the active
    object. The empty uses a single arrow display type and inherits the cursor's
    rotation.

    Returns:
        The newly created empty object.
    """
    obj = get_active_object()
    scene = get_bpy_context().scene
    empty_name = get_unique_name('Decal', get_bpy_data().objects)
    empty = get_bpy_data().objects.new(empty_name, None)
    empty.empty_display_type = 'SINGLE_ARROW'
    custom_collection = obj.users_collection[0] if len(obj.users_collection) > 0 else None
    link_object(scene, empty, custom_collection)
    empty.location = scene.cursor.location.copy()
    empty.rotation_euler = scene.cursor.rotation_euler.copy()

    # Parent empty to active object
    empty.parent = obj
    empty.matrix_parent_inverse = obj.matrix_world.inverted()

    return empty
