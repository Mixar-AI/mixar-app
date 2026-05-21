# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main entity baking function - bakes procedural effects to layers/masks.

This module provides the main bake_to_entity function. Implementation is split
across helper modules for maintainability:
- bake_to_entity_helpers: Validation and state management
- bake_to_entity_setup: Object and vertex color setup
- bake_to_entity_nodes: Node creation and cleanup
- bake_to_entity_process: Image creation and processing
- bake_to_entity_loop: Bake loop helpers
"""

from mixar.config.logging_config import get_logger

import time

import bpy

from ....core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_mp_nodes
from ....core.layer.layer_utils import get_root_height_channel
from ....core.node.check_nodes import check_mp_linear_nodes
from ....core.node.node_utils import get_active_mpaint_node
from ....utils.blender_commons import get_active_material, get_active_object, remove_mesh_obj
from ....utils.constants import io_suffix

from ...udim.udim_utils import get_tile_numbers

from ..utils.bake_common import (
    prepare_bake_settings,
    prepare_other_objs_channels,
    prepare_other_objs_colors,
    recover_bake_settings,
    recover_other_objs_channels,
    remember_before_bake,
)
from .bake_to_entity_helpers import (
    calculate_bake_dimensions,
    calculate_position_bbox,
    flip_mesh_normals,
    get_bakeable_objs,
    get_bake_type,
    prepare_other_object_emissions,
    recover_material_polygon_data,
    recover_modifier_states,
    recover_other_object_emissions,
    store_material_polygon_data,
    store_modifier_states,
    validate_bake_inputs,
    validate_cage_object,
)
from .bake_to_entity_loop import (
    handle_main_image_result,
    log_bake_result,
    set_overwrite_filepath,
    setup_other_object_channel_bake,
    setup_other_object_emission_bake,
)
from .bake_to_entity_nodes import (
    cleanup_bake_nodes,
    create_bake_nodes,
    handle_node_creation_error,
)
from .bake_to_entity_process import (
    bake_other_object_alpha,
    create_bake_image,
    execute_bake,
    get_base_color,
    get_image_colorspace,
    handle_image_atlas,
    post_process_image,
    store_bake_info,
    update_channel_override,
)
from .bake_to_entity_setup import (
    cleanup_flow_vertex_colors,
    cleanup_temp_vertex_colors,
    get_other_objects,
    setup_cavity_vertex_colors,
    setup_flow_vertex_colors,
    setup_multires_levels,
    setup_objects_for_bake,
    setup_selected_vertices,
    setup_subdiv_for_bake,
)

logger = get_logger(__name__)

# Re-export all helper functions for backward compatibility
__all__ = [
    "bake_to_entity",
    # From bake_to_entity_helpers
    "validate_bake_inputs",
    "validate_cage_object",
    "get_bakeable_objs",
    "calculate_bake_dimensions",
    "get_bake_type",
    "calculate_position_bbox",
    "store_modifier_states",
    "store_material_polygon_data",
    "recover_modifier_states",
    "recover_material_polygon_data",
    "prepare_other_object_emissions",
    "recover_other_object_emissions",
    "flip_mesh_normals",
    # From bake_to_entity_nodes
    "create_bake_nodes",
    "cleanup_bake_nodes",
    "handle_node_creation_error",
    # From bake_to_entity_setup
    "get_other_objects",
    "setup_subdiv_for_bake",
    "setup_objects_for_bake",
    "setup_selected_vertices",
    "setup_cavity_vertex_colors",
    "setup_flow_vertex_colors",
    "setup_multires_levels",
    "cleanup_flow_vertex_colors",
    "cleanup_temp_vertex_colors",
    # From bake_to_entity_process
    "get_image_colorspace",
    "get_base_color",
    "create_bake_image",
    "execute_bake",
    "post_process_image",
    "bake_other_object_alpha",
    "handle_image_atlas",
    "store_bake_info",
    "update_channel_override",
    # From bake_to_entity_loop
    "setup_other_object_channel_bake",
    "setup_other_object_emission_bake",
    "set_overwrite_filepath",
    "handle_main_image_result",
    "log_bake_result",
]


def bake_to_entity(bprops, overwrite_img=None, segment=None):
    """Bake procedural effects to a layer or mask entity.

    Parameters:
        bprops: Bake properties object with bake settings
        overwrite_img (Image, optional): Existing image to overwrite. Default None
        segment: Image atlas segment to use. Default None

    Returns:
        dict: Result dictionary with keys:
            - message (str): Error message if any
            - image (Image): Baked image
            - active_id (int): Index of created/updated layer
            - time_elapsed (float): Time taken to bake
    """
    T = time.time()
    mat = get_active_material()
    node = get_active_mpaint_node()
    mp = node.node_tree.mp
    scene = bpy.context.scene
    obj = get_active_object()
    channel_idx = (
        int(bprops.channel_idx)
        if "channel_idx" in bprops and len(mp.channels) > 0
        else -1
    )

    rdict = {"message": ""}

    # Validate inputs
    error = validate_bake_inputs(bprops, mp, obj)
    if error:
        rdict["message"] = error
        return rdict

    # Validate cage object
    cage_object, error = validate_cage_object(bprops, obj)
    if error:
        rdict["message"] = error
        return rdict

    # Get bakeable objects
    objs, error = get_bakeable_objs(mat, obj, cage_object, bprops)
    if error:
        rdict["message"] = error
        return rdict

    # Setup overwrite
    do_overwrite = False
    overwrite_image_name = ""
    if overwrite_img:
        do_overwrite = True
        overwrite_image_name = overwrite_img.name

    # Get other objects for other object baking
    other_objs, error = get_other_objects(bprops, mat, objs, overwrite_img, segment)
    if error:
        rdict["message"] = error
        return rdict

    # Prepare other objects channels/colors
    other_mats = []
    other_sockets = []
    other_defaults = []
    other_alpha_sockets = []
    other_alpha_defaults = []
    ch_other_objects = []
    ch_other_mats = []
    ch_other_sockets = []
    ch_other_defaults = []
    ch_other_default_weights = []
    ch_other_alpha_sockets = []
    ch_other_alpha_defaults = []
    ori_mat_no_nodes = []

    if bprops.type == "OTHER_OBJECT_EMISSION" and other_objs:
        (
            other_mats, other_sockets, other_defaults,
            other_alpha_sockets, other_alpha_defaults, ori_mat_no_nodes
        ) = prepare_other_objs_colors(mp, other_objs)
    elif bprops.type == "OTHER_OBJECT_CHANNELS" and other_objs:
        (
            ch_other_objects, ch_other_mats, ch_other_sockets,
            ch_other_defaults, ch_other_default_weights,
            ch_other_alpha_sockets, ch_other_alpha_defaults, ori_mat_no_nodes
        ) = prepare_other_objs_channels(mp, other_objs)

    # Get tile numbers
    tilenums = [1001]
    if bprops.use_udim:
        tilenums = get_tile_numbers(objs, bprops.uv_map)

    # Remember things
    book = remember_before_bake(mp, mat=mat)

    # Calculate dimensions and settings
    width, height, use_fxaa, use_ssaa, use_denoise = calculate_bake_dimensions(bprops)

    # Setup subdiv for bake
    subdiv_setup_changes = setup_subdiv_for_bake(mp, bprops)
    height_root_ch = get_root_height_channel(mp)

    # Setup objects for baking
    objs, temp_objs = setup_objects_for_bake(scene, objs, bprops, mp, other_objs)

    # Setup selected vertices
    fill_mode, obj_vertex_indices = setup_selected_vertices(objs, bprops)

    # Get alpha output for AO bake
    alpha_outp = None
    for c in mp.channels:
        if c.enable_alpha:
            alpha_outp = node.outputs.get(c.name + io_suffix["ALPHA"])
            if alpha_outp:
                break

    # Get bake type
    bake_type = get_bake_type(bprops, alpha_outp)

    # Prepare bake settings
    hide_other_objs = bprops.type != "AO" or bprops.only_local
    tile_x = width if bprops.samples <= 1 else 256
    tile_y = height if bprops.samples <= 1 else 256

    prepare_bake_settings(
        book, objs, mp,
        samples=bprops.samples, margin=bprops.margin, uv_map=bprops.uv_map,
        bake_type=bake_type, bake_device=bprops.bake_device,
        hide_other_objs=hide_other_objs, bake_from_multires=bprops.type.startswith("MULTIRES_"),
        tile_x=tile_x, tile_y=tile_y,
        use_selected_to_active=bprops.type.startswith("OTHER_OBJECT_"),
        max_ray_distance=bprops.max_ray_distance, cage_extrusion=bprops.cage_extrusion,
        source_objs=other_objs, use_denoising=False, margin_type=bprops.margin_type,
        use_cage=bprops.use_cage, cage_object_name=bprops.cage_object_name,
        normal_space="TANGENT" if bprops.type != "OBJECT_SPACE_NORMAL" else "OBJECT",
    )

    # Setup multires levels
    setup_multires_levels(objs, bprops)

    # Setup cavity vertex colors
    setup_cavity_vertex_colors(objs, bprops)

    # Setup flow vertex colors
    setup_flow_vertex_colors(objs, bprops)

    # Flip normals if needed
    if bprops.flip_normals:
        flip_mesh_normals(objs, other_objs)

    # Store modifier and material states
    disable_problematic_modifiers = bprops.type not in {
        "CAVITY", "POINTINESS", "BEVEL_NORMAL", "BEVEL_MASK"
    }
    mod_states = store_modifier_states(objs, bprops, other_objs, disable_problematic_modifiers)
    ori_mat_ids, ori_loop_locs = store_material_polygon_data(objs, mat, bprops)

    # Calculate bounding box for position map
    bbox_min, bbox_max = None, None
    if bprops.type == "POSITION" and bprops.position_normalize:
        bbox_min, bbox_max = calculate_position_bbox(objs)

    # Create bake nodes
    nodes, error = create_bake_nodes(mat, bprops, objs, bbox_min, bbox_max)
    if error:
        rdict["message"] = error
        handle_node_creation_error(mat, nodes, book, mp)
        return rdict

    # Configure world settings for alpha AO case
    if bprops.type == "AO" and alpha_outp:
        if hasattr(scene.cycles, "use_fast_gi"):
            scene.cycles.use_fast_gi = True
        if scene.world:
            scene.world.light_settings.distance = bprops.ao_distance

    # Get channel IDs and prepare other object emissions
    ch_ids = [0]
    all_other_mats = []
    ori_from_nodes = {}
    ori_from_sockets = {}

    if bprops.type == "OTHER_OBJECT_CHANNELS":
        ch_ids = [i for i, coo in enumerate(ch_other_objects) if len(coo) > 0]
        for oo in other_objs:
            for m in oo.data.materials:
                if m is None or not m.use_nodes:
                    continue
                if m not in all_other_mats:
                    all_other_mats.append(m)
        ori_from_nodes, ori_from_sockets = prepare_other_object_emissions(
            other_mats, all_other_mats, bprops.type
        )
    elif bprops.type == "OTHER_OBJECT_EMISSION":
        ori_from_nodes, ori_from_sockets = prepare_other_object_emissions(
            other_mats, all_other_mats, bprops.type
        )

    # Main bake loop
    active_id = None
    image = None

    for idx in ch_ids:
        image_name = bprops.name
        root_ch = mp.channels[idx] if bprops.type == "OTHER_OBJECT_CHANNELS" else None

        if bprops.type == "OTHER_OBJECT_CHANNELS":
            image_name += " " + mp.channels[idx].name
            setup_other_object_channel_bake(
                mp, idx, other_objs, ch_other_objects, ch_other_mats,
                ch_other_defaults, ch_other_default_weights, ch_other_sockets,
                all_other_mats, ori_from_nodes, ori_from_sockets
            )
            bake_type = "NORMAL" if root_ch.type == "NORMAL" else "EMIT"
        elif bprops.type == "OTHER_OBJECT_EMISSION":
            setup_other_object_emission_bake(other_mats, other_defaults, other_sockets)

        colorspace = get_image_colorspace(bprops, bake_type, root_ch)
        color = get_base_color(bprops, bake_type)

        # Create image
        image = create_bake_image(bprops, image_name, colorspace, color, width, height, tilenums)

        # Set filepath if overwriting
        if do_overwrite:
            set_overwrite_filepath(image, bprops, mp, idx, ch_ids, overwrite_image_name, segment)

        # Set bake image
        nodes.tex.image = image
        mat.node_tree.nodes.active = nodes.tex

        # Execute bake
        execute_bake(bprops, bake_type, scene)

        # Post-process image
        image = post_process_image(image, bprops, use_fxaa, use_ssaa, use_denoise, nodes.map_range)

        # Bake alpha for other object baking
        bake_other_object_alpha(
            image, nodes.tex, bprops, tilenums, scene, idx,
            ch_other_mats, ch_other_alpha_defaults, ch_other_alpha_sockets,
            other_mats, other_alpha_defaults, other_alpha_sockets
        )

        # HACK: Prevent tex node index confusion in Blender 4.5
        nodes.tex.image = None

        # Handle image atlas
        image, segment, new_segment_created = handle_image_atlas(image, bprops, segment, tilenums, mp)

        # Create or update layer/mask
        if idx == min(ch_ids):
            active_id = handle_main_image_result(
                mp, node, bprops, image, segment, do_overwrite,
                overwrite_image_name, channel_idx, new_segment_created
            )
        else:
            update_channel_override(mp, bprops, image, idx)

        # Store bake info
        store_bake_info(image, segment, bprops, other_objs, fill_mode, obj_vertex_indices)

    # Cleanup and recovery
    _cleanup_bake(
        mat, mp, node, nodes, objs, other_objs, temp_objs, bprops, book,
        height_root_ch, subdiv_setup_changes, mod_states, ori_mat_ids, ori_loop_locs,
        all_other_mats, other_mats, ori_from_nodes, ori_from_sockets, ori_mat_no_nodes
    )

    time_elapsed = time.time() - T
    log_bake_result(image, time_elapsed)

    rdict["active_id"] = active_id
    rdict["image"] = image
    rdict["time_elapsed"] = time_elapsed

    return rdict


def _cleanup_bake(mat, mp, node, nodes, objs, other_objs, temp_objs, bprops, book,
                  height_root_ch, subdiv_setup_changes, mod_states, ori_mat_ids, ori_loop_locs,
                  all_other_mats, other_mats, ori_from_nodes, ori_from_sockets, ori_mat_no_nodes):
    """Cleanup after baking."""
    # Recover other materials
    if bprops.type in {"OTHER_OBJECT_CHANNELS", "OTHER_OBJECT_EMISSION"}:
        mats = all_other_mats if bprops.type == "OTHER_OBJECT_CHANNELS" else other_mats
        recover_other_object_emissions(mats, ori_from_nodes, ori_from_sockets)
        recover_other_objs_channels(other_objs, ori_mat_no_nodes)

    # Remove temp bake nodes
    cleanup_bake_nodes(mat, nodes)

    # Recover states
    recover_modifier_states(objs, mod_states)
    recover_material_polygon_data(objs, ori_mat_ids, ori_loop_locs, bprops)

    # Delete temp vcol
    cleanup_temp_vertex_colors(objs)

    # Recover flip normals
    if bprops.flip_normals:
        flip_mesh_normals(objs, other_objs, flip=False)

    # Recover subdiv setup
    if height_root_ch and subdiv_setup_changes:
        height_root_ch.enable_subdiv_setup = not height_root_ch.enable_subdiv_setup

    # Remove flow vcols
    cleanup_flow_vertex_colors(objs, bprops)

    # Recover bake settings
    recover_bake_settings(book, mp, mat=mat)

    # Remove temporary objects
    if temp_objs:
        for o in temp_objs:
            try:
                remove_mesh_obj(o)
            except Exception as e:
                logger.warning("Failed to remove temp object: %s", e)

    # Check linear nodes
    check_mp_linear_nodes(mp, reconnect=True)

    # Reconnect and rearrange nodes
    reconnect_mp_nodes(node.node_tree)
    rearrange_mp_nodes(node.node_tree)
