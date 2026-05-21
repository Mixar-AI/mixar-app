# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for object-related baking operations."""

from mixar.config.logging_config import get_logger

import bpy

from ..utils.bake_common import (
    get_merged_mesh_objects,
    get_output_uv_names_from_geometry_nodes,
    is_join_objects_problematic,
)

logger = get_logger(__name__)


def get_bake_objects(obj, mat, get_scene_objects_func, get_uv_layers_func):
    """Get all objects to bake.

    Args:
        obj: The active object
        mat: The material
        get_scene_objects_func: Function to get scene objects
        get_uv_layers_func: Function to get UV layers for an object

    Returns:
        Tuple of (objects list, meshes list)
    """
    objs = [obj]
    meshes = [obj.data]
    if mat.users > 1:
        objs = []
        meshes = []
        for ob in get_scene_objects_func():
            if ob.type != "MESH":
                continue
            if ob.hide_viewport or ob.hide_render:
                continue
            if len(get_uv_layers_func(ob)) == 0:
                continue
            if len(ob.data.polygons) == 0:
                continue
            for i, m in enumerate(ob.data.materials):
                if m == mat:
                    ob.active_material_index = i
                    if ob not in objs and ob.data not in meshes:
                        objs.append(ob)
                        meshes.append(ob.data)
    return objs, meshes


def setup_multi_material(objs, mat, uv_map, force_bake_all_polygons, get_uv_layers_func):
    """Setup multi-material objects for baking.

    Args:
        objs: List of objects
        mat: The material
        uv_map: UV map name
        force_bake_all_polygons: Whether to force bake all polygons
        get_uv_layers_func: Function to get UV layers for an object

    Returns:
        Tuple of (original material indices dict, original loop locations dict)
    """
    from mathutils import Vector

    ori_mat_ids = {}
    ori_loop_locs = {}
    for ob in objs:
        ori_mat_ids[ob.name] = []
        ori_loop_locs[ob.name] = []

        if len(ob.data.materials) > 1:
            uv_layers = get_uv_layers_func(ob)
            uvl = uv_layers.get(uv_map)

            active_mat_id = [i for i, m in enumerate(ob.data.materials) if m == mat][0]
            for p in ob.data.polygons:
                if uvl and not force_bake_all_polygons:
                    uv_locs = []
                    for li in p.loop_indices:
                        uv_locs.append(uvl.data[li].uv.copy())
                        if p.material_index != active_mat_id:
                            uvl.data[li].uv = Vector((0.0, 0.0))
                    ori_loop_locs[ob.name].append(uv_locs)

                ori_mat_ids[ob.name].append(p.material_index)
                p.material_index = active_mat_id

    return ori_mat_ids, ori_loop_locs


def prepare_objects_for_bake(scene, objs, mp, mat):
    """Prepare objects for baking, potentially merging them.

    Args:
        scene: Blender scene
        objs: List of objects
        mp: Material properties
        mat: The material

    Returns:
        Tuple of (temp_objs, ori_objs)
    """
    any_uv_geonodes = False
    for o in objs:
        if any(get_output_uv_names_from_geometry_nodes(o)):
            any_uv_geonodes = True

    temp_objs = []
    ori_objs = []
    if (len(objs) > 1 or any_uv_geonodes) and not is_join_objects_problematic(mp, mat):
        ori_objs = objs
        temp_objs = [get_merged_mesh_objects(scene, objs)]

    return temp_objs, ori_objs


def recover_multi_material(objs, ori_mat_ids, ori_loop_locs, uv_map, get_uv_layers_func):
    """Recover multi-material setup.

    Args:
        objs: List of objects
        ori_mat_ids: Original material indices
        ori_loop_locs: Original loop locations
        uv_map: UV map name
        get_uv_layers_func: Function to get UV layers for an object
    """
    for ob in objs:
        if ori_mat_ids.get(ob.name):
            for i, p in enumerate(ob.data.polygons):
                if ori_mat_ids[ob.name][i] != p.material_index:
                    p.material_index = ori_mat_ids[ob.name][i]

        if ori_loop_locs.get(ob.name):
            uv_layers = get_uv_layers_func(ob)
            uvl = uv_layers.get(uv_map)
            if uvl:
                for i, p in enumerate(ob.data.polygons):
                    for j, li in enumerate(p.loop_indices):
                        uvl.data[li].uv = ori_loop_locs[ob.name][i][j]


def post_bake_operations(
    context, tree, mp, height_ch, ori_edit_mode, temp_objs,
    check_subdiv_setup_func, check_uv_nodes_func, check_start_end_root_ch_nodes_func,
    reconnect_mp_nodes_func, rearrange_mp_nodes_func, update_enable_baked_outside_func,
    remove_mesh_obj_func
):
    """Perform post-bake operations.

    Args:
        context: Blender context
        tree: Node tree
        mp: Material properties
        height_ch: Height channel
        ori_edit_mode: Whether was originally in edit mode
        temp_objs: Temporary objects to clean up
        check_subdiv_setup_func: Function to check subdiv setup
        check_uv_nodes_func: Function to check UV nodes
        check_start_end_root_ch_nodes_func: Function to check start/end nodes
        reconnect_mp_nodes_func: Function to reconnect mp nodes
        rearrange_mp_nodes_func: Function to rearrange mp nodes
        update_enable_baked_outside_func: Function to update baked outside
        remove_mesh_obj_func: Function to remove mesh objects
    """
    import bpy

    # Check subdiv Setup
    if height_ch:
        check_subdiv_setup_func(height_ch)

    # Update global uv
    check_uv_nodes_func(mp)

    # Check start and end nodes
    check_start_end_root_ch_nodes_func(tree)

    # Rearrange
    reconnect_mp_nodes_func(tree)
    rearrange_mp_nodes_func(tree)

    # Revert back to edit mode
    if ori_edit_mode:
        bpy.ops.object.mode_set(mode="EDIT")

    # Refresh active channel index
    mp.active_channel_index = mp.active_channel_index

    # Update UI
    mpui = context.window_manager.mpui
    mpui.need_update = True

    # Refresh bake target index
    if len(mp.bake_targets) > 0:
        if mpui.show_bake_targets:
            mp.active_bake_target_index = mp.active_bake_target_index

    # Update baked outside nodes
    update_enable_baked_outside_func(mp, context)

    # Remove temporary objects
    if temp_objs:
        for o in temp_objs:
            remove_mesh_obj_func(o)
