# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper utilities for entity baking operations."""

from mixar.config.logging_config import get_logger

import bpy
from mathutils import Vector

from ....core.element.get_elements import get_multires_modifier
from ....core.layer.layer_utils import get_uv_layers
from ....core.node.get_nodes import get_material_output
from ....utils.blender_commons import get_active_object, get_viewport_context

from ...udim.udim_utils import get_tile_numbers

from ..utils.bake_common import (
    TEMP_EMISSION,
    get_bakeable_objects_and_meshes,
    is_object_bakeable,
)

logger = get_logger(__name__)


def validate_bake_inputs(bprops, mp, obj):
    """Validate bake input parameters.

    Parameters:
        bprops: Bake properties object with bake settings
        mp: Material properties
        obj: Active object

    Returns:
        str: Error message if validation fails, empty string if valid
    """
    if bprops.type == "SELECTED_VERTICES" and obj.mode != "EDIT":
        return "Should be in edit mode!"

    if bprops.target_type == "MASK" and len(mp.layers) == 0:
        return "Mask need active layer!"

    if (hasattr(obj, "hide_viewport") and obj.hide_viewport) or obj.hide_render:
        return "Please unhide render and viewport of active object!"

    if bprops.type == "FLOW" and (
        bprops.uv_map == "" or bprops.uv_map_1 == "" or bprops.uv_map == bprops.uv_map_1
    ):
        return "UVMap and Straight UVMap cannot be the same or empty!"

    return ""


def validate_cage_object(bprops, obj):
    """Validate cage object for other object baking.

    Parameters:
        bprops: Bake properties object
        obj: Active object

    Returns:
        tuple: (cage_object or None, error message)
    """
    cage_object = None
    if (
        bprops.type.startswith("OTHER_OBJECT_")
        and bprops.use_cage
        and bprops.cage_object_name != ""
    ):
        cage_object = bpy.data.objects.get(bprops.cage_object_name)
        if cage_object:
            if any(
                [mod for mod in cage_object.modifiers if mod.type not in {"ARMATURE"}]
            ) or any([mod for mod in obj.modifiers if mod.type not in {"ARMATURE"}]):
                return None, "Mesh modifiers is not working with cage object for now!"

            if len(cage_object.data.polygons) != len(obj.data.polygons):
                return None, (
                    "Invalid cage object, the cage mesh must have the same number of faces as the active object!"
                )

    return cage_object, ""


def get_bakeable_objs(mat, obj, cage_object, bprops):
    """Get list of bakeable objects.

    Parameters:
        mat: Active material
        obj: Active object
        cage_object: Cage object if any
        bprops: Bake properties

    Returns:
        tuple: (list of objects, error message)
    """
    objs = [obj] if is_object_bakeable(obj) else []
    if mat.users > 1:
        objs, meshes = get_bakeable_objects_and_meshes(mat, cage_object)

    # Count multires objects
    multires_count = 0
    if bprops.type.startswith("MULTIRES_"):
        for ob in objs:
            if get_multires_modifier(ob):
                multires_count += 1

    if not objs or (bprops.type.startswith("MULTIRES_") and multires_count == 0):
        return [], "No valid objects found to bake!"

    return objs, ""


def calculate_bake_dimensions(bprops):
    """Calculate bake image dimensions.

    Parameters:
        bprops: Bake properties

    Returns:
        tuple: (width, height, use_fxaa, use_ssaa, use_denoise)
    """
    # FXAA doesn't work with hdr image
    # FXAA also does not works well with baked image with alpha
    use_fxaa = (
        not bprops.hdr and bprops.fxaa and not bprops.type.startswith("OTHER_OBJECT_")
    )

    # For now SSAA only works with other object baking
    use_ssaa = bprops.ssaa and bprops.type.startswith("OTHER_OBJECT_")

    # Denoising only available for AO bake for now
    use_denoise = bprops.denoise and bprops.type in {"AO", "BEVEL_MASK", "BEVEL_NORMAL"}

    # SSAA will multiply size by 2 then resize it back
    if use_ssaa:
        width = bprops.width * 2
        height = bprops.height * 2
    else:
        width = bprops.width
        height = bprops.height

    return width, height, use_fxaa, use_ssaa, use_denoise


def get_bake_type(bprops, alpha_outp):
    """Determine the bake type based on properties.

    Parameters:
        bprops: Bake properties
        alpha_outp: Alpha output socket if any

    Returns:
        str: Bake type string
    """
    if bprops.type == "AO":
        if alpha_outp:
            return "AO"
        else:
            return "COMBINED"
    elif bprops.type == "MULTIRES_NORMAL":
        return "NORMALS"
    elif bprops.type == "MULTIRES_DISPLACEMENT":
        return "DISPLACEMENT"
    elif bprops.type in {"OTHER_OBJECT_NORMAL", "OBJECT_SPACE_NORMAL", "BEVEL_NORMAL"}:
        return "NORMAL"
    else:
        return "EMIT"


def calculate_position_bbox(objs):
    """Calculate combined bounding box for position map normalization.

    Parameters:
        objs: List of objects to get bounding box from

    Returns:
        tuple: (bbox_min, bbox_max) as lists of 3 floats each
    """
    bbox_min = [float('inf'), float('inf'), float('inf')]
    bbox_max = [float('-inf'), float('-inf'), float('-inf')]

    for bake_obj in objs:
        # Get world-space bounding box corners
        bbox_corners = [bake_obj.matrix_world @ Vector(corner) for corner in bake_obj.bound_box]
        for corner in bbox_corners:
            for i in range(3):
                bbox_min[i] = min(bbox_min[i], corner[i])
                bbox_max[i] = max(bbox_max[i], corner[i])

    # Fallback if no valid bounding box
    if any(v == float('inf') for v in bbox_min) or any(v == float('-inf') for v in bbox_max):
        bbox_min = [-1.0, -1.0, -1.0]
        bbox_max = [1.0, 1.0, 1.0]

    return bbox_min, bbox_max


def store_modifier_states(objs, bprops, other_objs, disable_problematic_modifiers):
    """Store original modifier states for later recovery.

    Parameters:
        objs: List of objects
        bprops: Bake properties
        other_objs: List of other objects for transfer baking
        disable_problematic_modifiers: Whether to disable problematic modifiers

    Returns:
        dict: Dictionary containing original states
    """
    from ..utils.bake_common import get_problematic_modifiers

    ori_mods = {}
    ori_viewport_mods = {}
    ori_mat_ids = {}
    ori_loop_locs = {}
    ori_multires_levels = {}

    for ob in objs:
        # Disable few modifiers
        ori_mods[ob.name] = [m.show_render for m in ob.modifiers]
        ori_viewport_mods[ob.name] = [m.show_viewport for m in ob.modifiers]

        if bprops.type.startswith("MULTIRES_"):
            mul = get_multires_modifier(ob)
            multires_index = 99
            if mul:
                for i, m in enumerate(ob.modifiers):
                    if m == mul:
                        multires_index = i
                    if i > multires_index:
                        m.show_render = False
                        m.show_viewport = False
        elif disable_problematic_modifiers and ob not in other_objs:
            for m in get_problematic_modifiers(ob):
                m.show_render = False

        ori_mat_ids[ob.name] = []
        ori_loop_locs[ob.name] = []

        if (
            bprops.subsurf_influence
            and not bprops.use_baked_disp
            and not bprops.type.startswith("MULTIRES_")
        ):
            for m in ob.modifiers:
                if m.type == "MULTIRES":
                    ori_multires_levels[ob.name] = m.render_levels
                    m.render_levels = m.total_levels
                    break

    return {
        "ori_mods": ori_mods,
        "ori_viewport_mods": ori_viewport_mods,
        "ori_mat_ids": ori_mat_ids,
        "ori_loop_locs": ori_loop_locs,
        "ori_multires_levels": ori_multires_levels,
    }


def store_material_polygon_data(objs, mat, bprops):
    """Store material and polygon data for multi-material objects.

    Parameters:
        objs: List of objects
        mat: Active material
        bprops: Bake properties

    Returns:
        tuple: (ori_mat_ids dict, ori_loop_locs dict)
    """
    ori_mat_ids = {}
    ori_loop_locs = {}

    for ob in objs:
        ori_mat_ids[ob.name] = []
        ori_loop_locs[ob.name] = []

        if len(ob.data.materials) > 1:
            active_mat_id = [i for i, m in enumerate(ob.data.materials) if m == mat]
            if active_mat_id:
                active_mat_id = active_mat_id[0]
            else:
                continue

            uv_layers = get_uv_layers(ob)
            uvl = uv_layers.get(bprops.uv_map)

            for p in ob.data.polygons:
                # Set uv location to (0,0) if not using current material
                if uvl and not bprops.force_bake_all_polygons:
                    uv_locs = []
                    for li in p.loop_indices:
                        uv_locs.append(uvl.data[li].uv.copy())
                        if p.material_index != active_mat_id:
                            uvl.data[li].uv = Vector((0.0, 0.0))

                    ori_loop_locs[ob.name].append(uv_locs)

                # Need to assign all polygon to active material
                ori_mat_ids[ob.name].append(p.material_index)
                p.material_index = active_mat_id

    return ori_mat_ids, ori_loop_locs


def recover_modifier_states(objs, states):
    """Recover original modifier states.

    Parameters:
        objs: List of objects
        states: Dictionary containing original states
    """
    ori_mods = states["ori_mods"]
    ori_viewport_mods = states["ori_viewport_mods"]
    ori_multires_levels = states["ori_multires_levels"]

    for ob in objs:
        # Recover modifiers
        for i, m in enumerate(ob.modifiers):
            if i >= len(ori_mods.get(ob.name, [])):
                break
            if ori_mods[ob.name][i] != m.show_render:
                m.show_render = ori_mods[ob.name][i]
            if i >= len(ori_viewport_mods.get(ob.name, [])):
                break
            if ori_viewport_mods[ob.name][i] != m.show_render:
                m.show_viewport = ori_viewport_mods[ob.name][i]

        # Recover multires levels
        for m in ob.modifiers:
            if m.type == "MULTIRES" and ob.name in ori_multires_levels:
                m.render_levels = ori_multires_levels[ob.name]
                break


def recover_material_polygon_data(objs, ori_mat_ids, ori_loop_locs, bprops):
    """Recover material and polygon data.

    Parameters:
        objs: List of objects
        ori_mat_ids: Original material indices
        ori_loop_locs: Original UV loop locations
        bprops: Bake properties
    """
    for ob in objs:
        # Recover material index
        if ori_mat_ids.get(ob.name):
            for i, p in enumerate(ob.data.polygons):
                if ori_mat_ids[ob.name][i] != p.material_index:
                    p.material_index = ori_mat_ids[ob.name][i]

        if ori_loop_locs.get(ob.name):
            # Get uv map
            uv_layers = get_uv_layers(ob)
            uvl = uv_layers.get(bprops.uv_map)

            # Recover uv locations
            if uvl:
                for i, p in enumerate(ob.data.polygons):
                    for j, li in enumerate(p.loop_indices):
                        uvl.data[li].uv = ori_loop_locs[ob.name][i][j]


def prepare_other_object_emissions(other_mats, all_other_mats, bprops_type):
    """Prepare emission nodes for other object materials.

    Parameters:
        other_mats: List of other materials (for emission type)
        all_other_mats: List of all other materials (for channels type)
        bprops_type: Bake type string

    Returns:
        tuple: (ori_from_nodes dict, ori_from_sockets dict)
    """
    ori_from_nodes = {}
    ori_from_sockets = {}

    mats = all_other_mats if bprops_type == "OTHER_OBJECT_CHANNELS" else other_mats

    for m in mats:
        from_node = ""
        from_socket = ""
        mout = get_material_output(m)
        if mout:
            for l in mout.inputs[0].links:
                from_node = l.from_node.name
                from_socket = l.from_socket.name

            # Create temporary emission
            temp_emi = m.node_tree.nodes.get(TEMP_EMISSION)
            if not temp_emi:
                temp_emi = m.node_tree.nodes.new("ShaderNodeEmission")
                temp_emi.name = TEMP_EMISSION
                m.node_tree.links.new(temp_emi.outputs[0], mout.inputs[0])

        ori_from_nodes[m.name] = from_node
        ori_from_sockets[m.name] = from_socket

    return ori_from_nodes, ori_from_sockets


def recover_other_object_emissions(mats, ori_from_nodes, ori_from_sockets):
    """Recover other object emission nodes.

    Parameters:
        mats: List of materials
        ori_from_nodes: Original from node names
        ori_from_sockets: Original from socket names
    """
    for m in mats:
        # Set back original socket
        mout = get_material_output(m)
        if mout:
            nod = m.node_tree.nodes.get(ori_from_nodes.get(m.name, ""))
            if nod:
                soc = nod.outputs.get(ori_from_sockets.get(m.name, ""))
                if soc:
                    m.node_tree.links.new(soc, mout.inputs[0])

        # Remove temp emission
        temp_emi = m.node_tree.nodes.get(TEMP_EMISSION)
        if temp_emi:
            m.node_tree.nodes.remove(temp_emi)


def flip_mesh_normals(objs, other_objs, flip=True):
    """Flip or restore mesh normals.

    Parameters:
        objs: List of mesh objects
        other_objs: Other objects to deselect during operation
        flip: If True, flip normals; if False, restore
    """
    # Deselect other objects first
    for o in other_objs:
        o.select_set(False)

    # Mesh operators need viewport context
    viewport_ctx = get_viewport_context()

    if viewport_ctx:
        with bpy.context.temp_override(**viewport_ctx):
            bpy.ops.object.mode_set(mode="EDIT")
            try:
                bpy.ops.mesh.reveal()
                bpy.ops.mesh.select_all(action="SELECT")
                bpy.ops.mesh.flip_normals()
            finally:
                bpy.ops.object.mode_set(mode="OBJECT")
    else:
        # Fallback without context override
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            bpy.ops.mesh.reveal()
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.flip_normals()
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")

    # Reselect other objects
    for o in other_objs:
        o.select_set(True)
