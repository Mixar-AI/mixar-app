# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Execution helpers for entity baking - other object setup, results, cleanup."""

from mixar.config.logging_config import get_logger

import bpy

from ....core.element.update_image import replace_image
from ....core.element.update_uv import refresh_temp_uv, set_uv_neighbor_resolution
from ....core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_mp_nodes
from ....core.layer.get_layers import get_entities_with_specific_image
from ....core.node.check_nodes import check_mp_linear_nodes
from ....core.node.get_nodes import get_channel_source, get_channel_source_1, get_material_output
from ....utils.blender_commons import get_active_object, remove_mesh_obj
from ....utils.common import set_entity_prop_value

from ...image_atlas.image_atlas_operators_helper import get_entities_with_specific_segment
from ...image_atlas.image_atlas_utils import replace_segment_with_image, set_segment_mapping

from ..utils.bake_common import TEMP_EMISSION, recover_bake_settings, recover_other_objs_channels
from .bake_to_entity_helpers import (
    flip_mesh_normals,
    recover_material_polygon_data,
    recover_modifier_states,
    recover_other_object_emissions,
)
from .bake_to_entity_nodes import cleanup_bake_nodes
from .bake_to_entity_process import create_layer_from_bake, create_mask_from_bake
from .bake_to_entity_setup import cleanup_flow_vertex_colors, cleanup_temp_vertex_colors
from ..utils.bake_result_handlers import update_channel_override

logger = get_logger(__name__)


def setup_other_object_channel_bake(mp, idx, other_objs, ch_other_objects, ch_other_mats,
                                    ch_other_defaults, ch_other_default_weights, ch_other_sockets,
                                    all_other_mats, ori_from_nodes, ori_from_sockets):
    """Setup other object channel baking."""
    root_ch = mp.channels[idx]

    # Hide irrelevant objects
    for oo in other_objs:
        if oo not in ch_other_objects[idx]:
            oo.hide_render = True
        else:
            oo.hide_render = False

    if root_ch.type == "NORMAL":
        for m in all_other_mats:
            mout = get_material_output(m)
            if mout:
                nod = m.node_tree.nodes.get(ori_from_nodes.get(m.name, ""))
                if nod:
                    soc = nod.outputs.get(ori_from_sockets.get(m.name, ""))
                    if soc:
                        m.node_tree.links.new(soc, mout.inputs[0])
    else:
        connected_mats = []
        for j, m in enumerate(ch_other_mats[idx]):
            if m in connected_mats:
                continue
            default = ch_other_defaults[idx][j]
            default_weight = ch_other_default_weights[idx][j]
            socket = ch_other_sockets[idx][j]

            temp_emi = m.node_tree.nodes.get(TEMP_EMISSION)
            if not temp_emi:
                continue

            if len(temp_emi.outputs[0].links) == 0:
                mout = get_material_output(m)
                m.node_tree.links.new(temp_emi.outputs[0], mout.inputs[0])

            if default is not None:
                if type(default) == float:
                    temp_emi.inputs[0].default_value = (default, default, default, 1.0)
                else:
                    temp_emi.inputs[0].default_value = (default[0], default[1], default[2], 1.0)
                for l in temp_emi.inputs[0].links:
                    m.node_tree.links.remove(l)
            elif socket:
                m.node_tree.links.new(socket, temp_emi.inputs[0])

            temp_emi.inputs[1].default_value = default_weight
            connected_mats.append(m)


def setup_other_object_emission_bake(other_mats, other_defaults, other_sockets):
    """Setup other object emission baking."""
    for i, m in enumerate(other_mats):
        default = other_defaults[i]
        socket = other_sockets[i]

        temp_emi = m.node_tree.nodes.get(TEMP_EMISSION)
        if not temp_emi:
            continue

        if default is not None:
            if type(default) == float:
                temp_emi.inputs[0].default_value = (default, default, default, 1.0)
            else:
                temp_emi.inputs[0].default_value = (default[0], default[1], default[2], 1.0)
        elif socket:
            m.node_tree.links.new(socket, temp_emi.inputs[0])


def set_overwrite_filepath(image, bprops, mp, idx, ch_ids, overwrite_image_name, segment):
    """Set image filepath when overwriting."""
    overwrite_img = bpy.data.images.get(overwrite_image_name)
    if idx == min(ch_ids):
        if not overwrite_img.packed_file and overwrite_img.filepath != "":
            image.filepath = overwrite_img.filepath
    else:
        layer = mp.layers[mp.active_layer_index]
        root_ch = mp.channels[idx]
        ch = layer.channels[idx]

        if root_ch.type == "NORMAL":
            source = get_channel_source_1(ch, layer)
        else:
            source = get_channel_source(ch, layer)

        if (source and hasattr(source, "image") and source.image
            and not source.image.packed_file and source.image.filepath != ""):
            image.filepath = source.image.filepath


def handle_main_image_result(mp, node, bprops, image, segment, do_overwrite,
                             overwrite_image_name, channel_idx, new_segment_created):
    """Handle the main image result (create layer/mask or update existing).

    For PREVIEW mode:
    - If apply_to_fill_layer is True and bake type is AO, update Fill layer's AO channel
    - Otherwise, just return without creating any entities (preview only)

    For LAYER/MASK modes:
    - Create new layer or mask as before
    """
    # Handle PREVIEW mode with apply_to_fill_layer (material initialization AO bake)
    if bprops.target_type == "PREVIEW" and bprops.apply_to_fill_layer:
        if bprops.type == 'AO' and mp.layers:
            for i, layer in enumerate(mp.layers):
                if layer.type == 'COLOR':
                    mp.active_layer_index = i
                    update_channel_override(mp, bprops, image, channel_idx)
                    return i
        return mp.active_layer_index

    # Handle regular PREVIEW mode - just return without creating entities
    if bprops.target_type == "PREVIEW":
        return mp.active_layer_index

    if do_overwrite:
        overwrite_img = bpy.data.images.get(overwrite_image_name)
        active_id = mp.active_layer_index

        if overwrite_img != image:
            if segment and not bprops.use_image_atlas:
                entities = replace_segment_with_image(mp, segment, image)
                segment = None
            else:
                entities = replace_image(overwrite_img, image, mp, bprops.uv_map)
        elif segment:
            entities = get_entities_with_specific_segment(mp, segment)
        else:
            entities = get_entities_with_specific_image(mp, image)

        for ent in entities:
            if new_segment_created:
                ent.segment_name = segment.name
                set_segment_mapping(ent, segment, image)

            if ent.uv_name != bprops.uv_map:
                ent.uv_name = bprops.uv_map

            if bprops.type == "AO" and ent.type == "AO":
                set_entity_prop_value(ent, "ao_distance", bprops.ao_distance)
            elif bprops.type == "BEVEL_MASK" and ent.type == "EDGE_DETECT":
                set_entity_prop_value(ent, "edge_detect_radius", bprops.bevel_radius)

        if bprops.target_type == "LAYER":
            layer_ids = [i for i, l in enumerate(mp.layers) if l in entities]
            if entities and mp.active_layer_index not in layer_ids:
                active_id = layer_ids[0]
            refresh_temp_uv(get_active_object(), mp.layers[active_id])
            set_uv_neighbor_resolution(mp.layers[active_id])
        elif bprops.target_type == "MASK":
            masks = []
            for l in mp.layers:
                masks.extend([m for m in l.masks if m in entities])
            if masks:
                masks[0].active_edit = True
                refresh_temp_uv(get_active_object(), masks[0])
                set_uv_neighbor_resolution(masks[0])
    elif bprops.target_type == "LAYER":
        active_id = create_layer_from_bake(mp, node, bprops, image, segment, channel_idx)
    else:
        active_id = create_mask_from_bake(mp, bprops, image, segment)

    return active_id


def cleanup_bake(mat, mp, node, nodes, objs, other_objs, temp_objs, bprops, book,
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


def log_result(image, time_elapsed):
    """Log bake result."""
    if image:
        logger.info(
            "BAKE TO LAYER: Baking %s is done in %s seconds!",
            image.name, "{:0.2f}".format(time_elapsed)
        )
    else:
        logger.warning(
            "BAKE TO LAYER: No image created! Executed in %s seconds!",
            "{:0.2f}".format(time_elapsed)
        )
