# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...utils.blender_commons import get_bpy_context, get_bpy_data, get_scene_objects
from ..layer.layer_utils import get_uv_layers


def get_materials_using_mp(mp):
    """Get all materials that use a specific MPaint node.

    Searches through all materials in the Blender data to find those that
    contain the specified MPaint (mp) node tree instance.

    Parameters
    ----------
    mp : bpy.types.NodeTree
        The MPaint node tree to search for in materials.

    Returns
    -------
    list of bpy.types.Material
        A list of materials that contain the specified MPaint node.
        Returns an empty list if no materials are found.
    """
    mats = []
    for mat in get_bpy_data().materials:
        if not mat.use_nodes: continue
        for node in mat.node_tree.nodes:
            if node.type == 'GROUP' and node.node_tree and node.node_tree.mp == mp and mat not in mats:
                mats.append(mat)
    return mats

def get_all_materials_with_mp_nodes(mesh_only=True):
    """Get all materials from scene objects that contain MPaint nodes.

    Iterates through scene objects and collects all unique materials that
    contain MPaint (GROUP) nodes marked with is_mpaint_node flag.

    Parameters
    ----------
    mesh_only : bool, optional
        If True, only consider materials from mesh objects.
        If False, consider materials from all object types.
        Default is True.

    Returns
    -------
    list of bpy.types.Material
        A list of unique materials containing MPaint nodes.
        Returns an empty list if no materials with MPaint nodes are found.
    """
    mats = []

    for obj in get_scene_objects():
        if mesh_only and obj.type != 'MESH': continue
        if not hasattr(obj, 'data') or not hasattr(obj.data, 'materials'): continue
        for mat in obj.data.materials:
            if any([n for n in mat.node_tree.nodes if n.type == 'GROUP' and n.node_tree and n.node_tree.mp.is_mpaint_node]):
                if mat not in mats:
                    mats.append(mat)

    return mats

def get_all_materials_with_tree(tree):
    """Get all materials that contain a specific node tree.

    Searches through all materials in Blender data to find those that
    contain GROUP nodes with the specified node tree.

    Parameters
    ----------
    tree : bpy.types.NodeTree
        The node tree to search for in materials.

    Returns
    -------
    list of bpy.types.Material
        A list of unique materials that contain the specified node tree.
        Returns an empty list if no materials are found.
    """
    mats = []

    for mat in get_bpy_data().materials:
        if not mat.node_tree: continue
        for node in mat.node_tree.nodes:
            if node.type == 'GROUP' and node.node_tree == tree and mat not in mats:
                mats.append(mat)

    return mats

def get_all_objects_with_same_materials(mat, mesh_only=False, uv_name='', selected_only=False):
    """Get all objects in the scene that use a specific material.

    Searches through scene objects to find all that have the specified material
    assigned. Can be filtered by object type, UV layer presence, and selection status.

    Parameters
    ----------
    mat : bpy.types.Material
        The material to search for in objects.
    mesh_only : bool, optional
        If True, only return mesh objects with the material.
        If False, return all object types that have the material.
        Default is False.
    uv_name : str, optional
        If specified, only return objects that have a UV layer with this name.
        If empty string, UV layer check is skipped.
        Default is '' (empty string).
    selected_only : bool, optional
        If True, only search through selected objects (or active object if none selected).
        If False, search through all scene objects.
        Default is False.

    Returns
    -------
    list of bpy.types.Object
        A list of objects that have the specified material assigned.
        Returns an empty list if no objects with the material are found.
        Objects without data, without polygons (when applicable), or without
        the specified UV layer are excluded.
    """
    objs = []

    if selected_only:
        if len(get_bpy_context().selected_objects) > 0:
            objects = get_bpy_context().selected_objects
        else: objects = [get_bpy_context().object]
    else: objects = get_scene_objects()

    for obj in objects:
        # Skip objects without data
        if not obj or not obj.data:
            continue

        if uv_name != '':
            uv_layers = get_uv_layers(obj)
            if not uv_layers or not uv_layers.get(uv_name): continue

        if hasattr(obj.data, 'polygons') and len(obj.data.polygons) == 0: continue

        if mesh_only:
            if obj.type != 'MESH': continue
            if len(obj.data.polygons) == 0: continue
        if not hasattr(obj.data, 'materials'): continue
        for m in obj.data.materials:
            if m == mat: # and obj not in objs:
                objs.append(obj)
                break

    return objs
