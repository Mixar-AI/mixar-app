# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Setup and preparation functions for entity baking."""

from mixar.config.logging_config import get_logger

import math
import time

import bmesh
import bpy

from ....core.element.create_vcol import new_vertex_color
from ....core.element.get_elements import get_multires_modifier
from ....core.element.get_vcol import get_flow_vcol
from ....core.element.update_vcol import set_active_vertex_color
from ....core.layer.check_layers import get_first_vdm_layer
from ....core.layer.layer_utils import get_root_height_channel, get_uv_layers
from ....utils.blender_commons import (
    get_object_parent_layer_collections,
    get_scene_objects,
    get_viewport_context,
    remove_datablock,
    set_active_object,
)
from ....utils.constants import FLOW_VCOL

from ...vector_displacement.vector_displacement_lib import get_vdm_loader_geotree
from ...vector_displacement.vector_displacement_utils import (
    get_combined_vdm_image,
    get_tangent_bitangent_images,
)

from ..utils.bake_common import (
    TEMP_VCOL,
    get_duplicated_mesh_objects,
    get_merged_mesh_objects,
    is_join_objects_problematic,
)

logger = get_logger(__name__)


def get_other_objects(bprops, mat, objs, overwrite_img, segment):
    """Get other objects for other object baking.

    Parameters:
        bprops: Bake properties
        mat: Active material
        objs: List of bakeable objects
        overwrite_img: Existing image to overwrite if any
        segment: Image atlas segment if any

    Returns:
        tuple: (other_objs list, error message if any)
    """
    other_objs = []

    if not bprops.type.startswith("OTHER_OBJECT_"):
        return other_objs, ""

    # Get other objects based on selected objects with different material
    for o in bpy.context.selected_objects:
        if o in objs or not o.data or not hasattr(o.data, "materials"):
            continue
        if mat.name not in o.data.materials:
            other_objs.append(o)

    # Try to get other_objects from bake info
    if overwrite_img:
        bi = segment.bake_info if segment else overwrite_img.m_bake_info

        scene_objs = get_scene_objects()
        for oo in bi.other_objects:
            ooo = oo.object

            if ooo:
                # Check if object is on current view layer
                layer_cols = get_object_parent_layer_collections(
                    [], bpy.context.view_layer.layer_collection, ooo
                )
                if ooo not in other_objs and any(layer_cols):
                    other_objs.append(ooo)

    if not other_objs:
        if overwrite_img:
            return [], "No source objects found! They're probably deleted!"
        else:
            return [], "Source objects must be selected and it should have different material!"

    return other_objs, ""


def setup_subdiv_for_bake(mp, bprops):
    """Setup subdivision for baking.

    Parameters:
        mp: Material properties
        bprops: Bake properties

    Returns:
        bool: Whether subdiv setup was changed
    """
    subdiv_setup_changes = False
    height_root_ch = get_root_height_channel(mp)

    if (
        height_root_ch
        and bprops.use_baked_disp
        and not bprops.type.startswith("MULTIRES_")
    ):
        if not height_root_ch.enable_subdiv_setup:
            height_root_ch.enable_subdiv_setup = True
            subdiv_setup_changes = True

    return subdiv_setup_changes


def setup_cavity_with_vdm(scene, objs, bprops, mp):
    """Setup cavity baking with VDM/subdiv.

    Parameters:
        scene: Blender scene
        objs: List of objects
        bprops: Bake properties
        mp: Material properties

    Returns:
        tuple: (modified objs list, temp_objs list)
    """
    temp_objs = []
    height_root_ch = get_root_height_channel(mp)

    if bprops.type != "CAVITY" or not (bprops.subsurf_influence or bprops.use_baked_disp):
        return objs, temp_objs

    # NOTE: Baking cavity with subdiv setup can only happen if there's only one object and no UDIM
    if (
        len(objs) == 1
        and not bprops.use_udim
        and height_root_ch
        and height_root_ch.enable_subdiv_setup
    ):
        # Check if there's VDM layer
        vdm_layer = get_first_vdm_layer(mp)
        vdm_uv_name = vdm_layer.uv_name if vdm_layer else bprops.uv_map

        # Get baked combined vdm image
        combined_vdm_image = get_combined_vdm_image(
            objs[0], vdm_uv_name, width=bprops.width, height=bprops.height
        )

        # Bake tangent and bitangent
        tanimage, bitimage = get_tangent_bitangent_images(objs[0], bprops.uv_map)

        # Duplicate object
        objs = temp_objs = [
            get_merged_mesh_objects(
                scene, objs, True, disable_problematic_modifiers=False
            )
        ]

        # Use VDM loader geometry nodes
        set_active_object(objs[0])
        vdm_loader = get_vdm_loader_geotree(
            bprops.uv_map, combined_vdm_image, tanimage, bitimage, 1.0
        )
        bpy.ops.object.modifier_add(type="NODES")
        geomod = objs[0].modifiers[-1]
        geomod.node_group = vdm_loader
        bpy.ops.object.modifier_apply(modifier=geomod.name)

        # Remove temporary datas
        remove_datablock(bpy.data.node_groups, vdm_loader)
        remove_datablock(bpy.data.images, combined_vdm_image)
    else:
        objs = temp_objs = get_duplicated_mesh_objects(scene, objs, True)

    return objs, temp_objs


def setup_objects_for_bake(scene, objs, bprops, mp, other_objs):
    """Setup objects for baking (joining, duplication, etc.).

    Parameters:
        scene: Blender scene
        objs: List of objects
        bprops: Bake properties
        mp: Material properties
        other_objs: List of other objects for transfer baking

    Returns:
        tuple: (modified objs list, temp_objs list)
    """
    temp_objs = []

    # Cavity with subdiv/VDM has special handling
    if bprops.type == "CAVITY" and (bprops.subsurf_influence or bprops.use_baked_disp):
        objs, temp_objs = setup_cavity_with_vdm(scene, objs, bprops, mp)

    # Join objects then extend with other objects
    elif bprops.type.startswith("OTHER_OBJECT_"):
        if len(objs) > 1:
            objs = [get_merged_mesh_objects(scene, objs)]
            temp_objs = objs.copy()

        objs.extend(other_objs)

    # Join objects if the number of objects is higher than one
    elif (
        not bprops.type.startswith("MULTIRES_")
        and len(objs) > 1
        and not is_join_objects_problematic(mp)
    ):
        objs = temp_objs = [get_merged_mesh_objects(scene, objs, True)]

    return objs, temp_objs


def setup_selected_vertices(objs, bprops):
    """Setup for selected vertices baking.

    Parameters:
        objs: List of objects
        bprops: Bake properties

    Returns:
        tuple: (fill_mode string, obj_vertex_indices dict)
    """
    fill_mode = "FACE"
    obj_vertex_indices = {}

    if bprops.type != "SELECTED_VERTICES":
        return fill_mode, obj_vertex_indices

    if (
        bpy.context.tool_settings.mesh_select_mode[0]
        or bpy.context.tool_settings.mesh_select_mode[1]
    ):
        fill_mode = "VERTEX"

    edit_objs = [o for o in objs if o.mode == "EDIT"]

    for ob in edit_objs:
        mesh = ob.data
        bm = bmesh.from_edit_mesh(mesh)

        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        v_indices = []
        if fill_mode == "FACE":
            for face in bm.faces:
                if face.select:
                    v_indices.append(face.index)
        else:
            for vert in bm.verts:
                if vert.select:
                    v_indices.append(vert.index)

        obj_vertex_indices[ob.name] = v_indices

    bpy.ops.object.mode_set(mode="OBJECT")
    for ob in objs:
        try:
            vcol = new_vertex_color(ob, TEMP_VCOL, color_fill=(0.0, 0.0, 0.0, 1.0))
            set_active_vertex_color(ob, vcol)
        except:
            pass

    # Mesh operators need viewport context
    viewport_ctx = get_viewport_context()

    if viewport_ctx:
        with bpy.context.temp_override(**viewport_ctx):
            bpy.ops.object.mode_set(mode="EDIT")
            try:
                bpy.ops.mesh.y_vcol_fill(color_option="WHITE")
            finally:
                bpy.ops.object.mode_set(mode="OBJECT")
    else:
        # Fallback without context override
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            bpy.ops.mesh.y_vcol_fill(color_option="WHITE")
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

    return fill_mode, obj_vertex_indices


def setup_cavity_vertex_colors(objs, bprops):
    """Setup vertex colors for cavity baking.

    Parameters:
        objs: List of objects
        bprops: Bake properties
    """
    if bprops.type != "CAVITY":
        return

    tt = time.time()
    logger.info("BAKE TO LAYER: Applying subsurf/multires for Cavity bake...")

    # Set vertex color for cavity
    for ob in objs:
        set_active_object(ob)

        if bprops.subsurf_influence or bprops.use_baked_disp:
            need_to_be_applied_modifiers = []
            for m in ob.modifiers:
                if (
                    m.type in {"SUBSURF", "MULTIRES"}
                    and m.levels > 0
                    and m.show_viewport
                ):
                    # Set multires to the highest level
                    if m.type == "MULTIRES":
                        m.levels = m.total_levels

                    need_to_be_applied_modifiers.append(m)

                # Also apply displace
                if m.type == "DISPLACE" and m.show_viewport:
                    need_to_be_applied_modifiers.append(m)

            # Apply shape keys and modifiers
            if any(need_to_be_applied_modifiers):
                if ob.data.shape_keys:
                    bpy.ops.object.shape_key_remove(all=True, apply_mix=True)
                for m in need_to_be_applied_modifiers:
                    bpy.ops.object.modifier_apply(modifier=m.name)

        # Create new vertex color for dirt
        try:
            vcol = new_vertex_color(ob, TEMP_VCOL, color_fill=(1.0, 1.0, 1.0, 1.0))
            set_active_vertex_color(ob, vcol)
        except:
            pass

        # vertex_color_dirt requires viewport context
        viewport_ctx = get_viewport_context()
        if viewport_ctx:
            with bpy.context.temp_override(**viewport_ctx):
                bpy.ops.paint.vertex_color_dirt(dirt_angle=math.pi / 2)
        else:
            # Fallback without context override
            bpy.ops.paint.vertex_color_dirt(dirt_angle=math.pi / 2)

    logger.info(
        "BAKE TO LAYER: Applying subsurf/multires is done in %s seconds!",
        "{:0.2f}".format(time.time() - tt),
    )


def setup_flow_vertex_colors(objs, bprops):
    """Setup vertex colors for flow baking.

    Parameters:
        objs: List of objects
        bprops: Bake properties
    """
    if bprops.type != "FLOW":
        return

    bpy.ops.object.mode_set(mode="OBJECT")
    for ob in objs:
        uv_layers = get_uv_layers(ob)
        main_uv = uv_layers.get(bprops.uv_map)
        straight_uv = uv_layers.get(bprops.uv_map_1)

        if main_uv and straight_uv:
            flow_vcol = get_flow_vcol(ob, main_uv, straight_uv)


def setup_multires_levels(objs, bprops):
    """Setup multires modifier levels for baking.

    Parameters:
        objs: List of objects
        bprops: Bake properties
    """
    if not bprops.type.startswith("MULTIRES_"):
        return

    for ob in objs:
        mod = get_multires_modifier(ob)
        if mod and bprops.type.startswith("MULTIRES_"):
            mod.render_levels = bprops.multires_base
            mod.levels = bprops.multires_base


def cleanup_flow_vertex_colors(objs, bprops):
    """Remove flow vertex colors after baking.

    Parameters:
        objs: List of objects
        bprops: Bake properties
    """
    from ....core.node.node_utils import get_vertex_colors

    if bprops.type != "FLOW":
        return

    for ob in objs:
        vcols = get_vertex_colors(ob)
        flow_vcol = vcols.get(FLOW_VCOL)
        if flow_vcol:
            vcols.remove(flow_vcol)


def cleanup_temp_vertex_colors(objs):
    """Remove temporary vertex colors after baking.

    Parameters:
        objs: List of objects
    """
    from ....core.node.node_utils import get_vertex_colors

    for ob in objs:
        vcols = get_vertex_colors(ob)
        if vcols:
            vcol = vcols.get(TEMP_VCOL)
            if vcol:
                vcols.remove(vcol)
