# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mesh and object preparation utilities for baking."""

from mixar.config.logging_config import get_logger

import time

import bpy

from ....utils.blender_commons import (
    get_scene_objects,
    in_renderable_layer_collection,
    link_object,
    remove_datablock,
    set_active_object,
    set_object_select,
)
from ..operators.bake_uv_ops import get_output_uv_names_from_geometry_nodes
from ..utils.bake_validation import get_problematic_modifiers, is_object_bakeable

logger = get_logger(__name__)


def get_bakeable_objects_and_meshes(mat, cage_object=None):
    """Get list of bakeable objects and their meshes for a material.

    Args:
        mat: Blender material object.
        cage_object: Cage object to exclude, defaults to None.

    Returns:
        tuple: (objs, meshes) tuple containing lists of bakeable objects and meshes.
    """
    objs = []
    meshes = []

    for ob in get_scene_objects():
        if not is_object_bakeable(ob):
            continue
        if cage_object and cage_object == ob:
            continue

        # Do not bake objects with hide_render on
        if ob.hide_render:
            continue
        if not in_renderable_layer_collection(ob):
            continue

        for i, m in enumerate(ob.data.materials):
            if m == mat:
                ob.active_material_index = i
                if ob not in objs and ob.data not in meshes:
                    objs.append(ob)
                    meshes.append(ob.data)

    return objs, meshes


def get_duplicated_mesh_objects(scene, objs, hide_original=False):
    """Create duplicates of mesh objects for baking.

    Args:
        scene: Blender scene object.
        objs (list): List of objects to duplicate.
        hide_original (bool, optional): Hide original objects from rendering. Defaults to False.

    Returns:
        list: List of duplicated object instances.
    """
    tt = time.time()
    logger.info("Duplicating mesh(es) for baking...")

    new_objs = []

    for obj in objs:
        if obj.type != "MESH":
            continue
        new_obj = obj.copy()
        link_object(scene, new_obj)
        new_objs.append(new_obj)
        new_obj.data = new_obj.data.copy()

        # Hide render of original object
        if hide_original:
            obj.hide_render = True

    logger.info(
        "Duplicating mesh(es) is done in %s seconds!",
        "{:0.2f}".format(time.time() - tt),
    )
    return new_objs


def get_merged_mesh_objects(
    scene, objs, hide_original=False, disable_problematic_modifiers=True
):
    """Create a single merged mesh object from multiple objects.

    Args:
        scene: Blender scene object.
        objs (list): List of objects to merge.
        hide_original (bool, optional): Hide original objects from rendering. Defaults to False.
        disable_problematic_modifiers (bool, optional): Disable problematic modifiers before merge. Defaults to True.

    Returns:
        Object: The merged mesh object.
    """

    # Duplicate objects
    new_objs = get_duplicated_mesh_objects(scene, objs, hide_original)
    new_meshes = [obj.data for obj in new_objs]

    tt = time.time()
    logger.info("Merging mesh(es) for baking...")

    # Check if any objects use geometry nodes to output uv
    any_uv_geonodes = False
    for obj in new_objs:
        if any(get_output_uv_names_from_geometry_nodes(obj)):
            any_uv_geonodes = True

    # Select objects
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except:
        pass
    bpy.ops.object.select_all(action="DESELECT")

    max_levels = -1
    hi_obj = None
    for obj in new_objs:
        set_active_object(obj)
        set_object_select(obj, True)

        # Apply shape keys
        if obj.data.shape_keys:
            # Set active shape to make sure context will be correct
            if not obj.active_shape_key:
                obj.active_shape_key_index = 0
            bpy.ops.object.shape_key_remove(all=True, apply_mix=True)

        # Apply modifiers
        mnames = [m.name for m in obj.modifiers]
        problematic_modifiers = (
            get_problematic_modifiers(obj) if disable_problematic_modifiers else []
        )

        # Get all uv output from geometry nodes
        geo_uv_names = get_output_uv_names_from_geometry_nodes(obj)

        for mname in mnames:

            m = obj.modifiers[mname]

            if m not in problematic_modifiers:
                if m.type == "SUBSURF":
                    if m.render_levels > m.levels:
                        m.levels = m.render_levels
                elif m.type == "MULTIRES":
                    if m.total_levels > m.levels:
                        m.levels = m.total_levels

                # Only apply modifier with show viewport on
                if m.show_viewport:
                    try:
                        bpy.ops.object.modifier_apply(modifier=m.name)
                        continue
                    except Exception as e:
                        logger.error("Error applying modifier: %s", e)

            bpy.ops.object.modifier_remove(modifier=m.name)

        # HACK: Convert all geo uvs attribute to 2D vector
        # This is needed since it always produce 3D vector in Blender 3.5
        # 3D vector can't produce correct tangent so smooth bump can't be baked
        for guv in geo_uv_names:
            for i, attr in enumerate(obj.data.attributes):
                if attr and attr.name == guv:
                    obj.data.attributes.active_index = i
                    bpy.ops.geometry.attribute_convert(
                        domain="CORNER", data_type="FLOAT2"
                    )

    # Set first index as merged object
    merged_obj = new_objs[0]

    # Set active object
    set_active_object(merged_obj)
    if merged_obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    # Join
    bpy.ops.object.join()

    # Remove temp meshes
    for nm in new_meshes:
        if nm != merged_obj.data:
            remove_datablock(bpy.data.meshes, nm)

    logger.info(
        "Merging mesh(es) is done in %s seconds!",
        "{:0.2f}".format(time.time() - tt),
    )
    return merged_obj
