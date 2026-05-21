# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ...utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_bpy_data,
    get_scene_objects,
    remove_datablock,
)
from ...utils.common import (
    get_write_height,
    is_bump_distance_relevant,
    is_parallax_enabled,
    set_mix_clamp,
)
from ...utils.constants import (
    EMISSION_VIEWER,
    GAMMA,
    PARALLAX_PREP_SUFFIX,
    limited_mask_blend_types,
    nsew_letters,
    texcoord_lists,
)
from ...utils.math_utils import get_fine_bump_distance
from ..element.check_elements import (
    check_entity_image_flip_y,
    check_uvmap_on_other_objects_with_same_mat,
)
from ..element.check_processes import check_layer_bump_process
from ..element.check_uv import check_actual_uv_nodes
from ..element.update_uv import remove_uv_nodes
from ..io.input_outputs.input_outputs_nodes import (
    check_layer_channel_linear_node,
    check_layer_image_linear_node,
    check_layer_texcoord_nodes,
    check_mask_image_linear_node,
)
from ..io.input_outputs.input_outputs_layer_ios import check_layer_tree_ios
from ..io.input_outputs.input_outputs import create_decal_empty
from ..io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ..io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ..layer.check_layers import (
    check_layer_divider_alpha,
    get_layer_enabled,
    get_mask_enabled,
    is_height_process_needed,
    is_layer_using_normal_map,
    is_layer_using_vdisp_map,
    is_layer_using_vector,
    is_normal_process_needed,
    is_vdisp_process_needed,
)
from ..layer.get_channels import get_bump_chain, get_channel_enabled
from ..layer.layer_utils import (
    get_height_channel,
    get_layer_channel_index,
    get_layer_index,
    get_root_height_channel,
    get_transition_bump_channel,
    get_uv_layers,
    update_preview_mix,
)
from ..layer.mappings import is_mapping_possible
from ..lib.lib import *
from ..lib.lib_operations import (
    check_if_node_is_duplicated_from_lib,
    duplicate_lib_node_tree,
)
from ..modifier.modifier import check_modifiers_trees, disable_modifiers_tree
from ..node.create_nodes import (
    check_new_node,
    get_smooth_mix_node,
    new_mix_node,
    new_node,
    replace_new_node,
)
from ..node.get_nodes import get_layer_source, get_mask_source
from ..node.node_graph import (
    get_layer_channel_bump_distance,
    get_transition_bump_max_distance,
)
from ..node.node_utils import (
    copy_node_props,
    get_node_tree_lib,
    is_normal_height_input_connected,
    remove_node,
)
from ..node.update_nodes import (
    check_parallax_node,
    replace_new_mix_node,
    set_default_value,
)
from ..subtree.check_subtree import (
    check_mask_source_tree,
    disable_channel_source_tree,
    disable_layer_source_tree,
    enable_channel_source_tree,
    enable_layer_source_tree,
)
from ..subtree.get_subtree import (
    get_displacement_max_height,
    get_list_of_all_children_and_child_ids,
    get_list_of_parent_ids,
    get_transition_disp_delta,
    get_tree,
)
from .height_operations import update_displacement_height_ratio
from .check_channel_blend_nodes import check_parallax_prep_nodes


def check_uv_nodes(mp, generate_missings=False):
    """
    Check and update UV map nodes and generate missing UV maps if requested.

    Parameters:
        mp: MPaint object containing UV and layer data.
        generate_missings (optional): If True, generate missing UV maps on objects. Default: False.

    Returns:
        True if any changes were made (dirty state), False otherwise.
    """

    # Check for UV needed
    uv_names = []

    # Get active object
    obj = get_active_object()
    mat = get_active_material()

    dirty = False

    # Get baked uv name
    if mp.baked_uv_name != "":
        uv = mp.uvs.get(mp.baked_uv_name)
        if not uv:
            dirty = True
            uv = mp.uvs.add()
            uv.name = mp.baked_uv_name

        if uv.name not in uv_names:
            uv_names.append(uv.name)

    # Get height channel
    height_ch = get_root_height_channel(mp)

    if height_ch:

        # Set height channel main uv if its still empty
        if height_ch.main_uv == "":
            uv_layers = get_uv_layers(obj)
            if uv_layers and len(uv_layers) > 0:
                height_ch.main_uv = uv_layers[0].name
                check_uvmap_on_other_objects_with_same_mat(mat, height_ch.main_uv)

        uv = mp.uvs.get(height_ch.main_uv)
        if not uv:
            dirty = True
            uv = mp.uvs.add()
            uv.name = height_ch.main_uv

        if uv.name not in uv_names:
            uv_names.append(height_ch.main_uv)

    # Collect uv names from layers
    for layer in mp.layers:
        if layer.texcoord_type == "UV" and layer.uv_name != "":
            uv = mp.uvs.get(layer.uv_name)
            if not uv:
                dirty = True
                uv = mp.uvs.add()
                uv.name = layer.uv_name

            if uv.name not in uv_names:
                uv_names.append(uv.name)

        if layer.use_baked and layer.baked_uv_name != "":
            uv = mp.uvs.get(layer.baked_uv_name)
            if not uv:
                dirty = True
                uv = mp.uvs.add()
                uv.name = layer.baked_uv_name

            if uv.name not in uv_names:
                uv_names.append(uv.name)

        for mask in layer.masks:
            if mask.texcoord_type == "UV" and mask.uv_name != "":
                uv = mp.uvs.get(mask.uv_name)
                if not uv:
                    dirty = True
                    uv = mp.uvs.add()
                    uv.name = mask.uv_name

                if uv.name not in uv_names:
                    uv_names.append(uv.name)

            if mask.use_baked and mask.baked_uv_name != "":
                uv = mp.uvs.get(mask.baked_uv_name)
                if not uv:
                    dirty = True
                    uv = mp.uvs.add()
                    uv.name = mask.baked_uv_name

                if uv.name not in uv_names:
                    uv_names.append(uv.name)

    # Get unused uv objects
    unused_uvs = []
    unused_ids = []
    for i, uv in reversed(list(enumerate(mp.uvs))):
        if uv.name not in uv_names:
            unused_uvs.append(uv)
            unused_ids.append(i)

    # Check non uv texcoords
    used_texcoords = []
    for layer in mp.layers:
        if layer.texcoord_type != "UV" and layer.texcoord_type not in used_texcoords:
            used_texcoords.append(layer.texcoord_type)

        for mask in layer.masks:
            if mask.texcoord_type != "UV" and mask.texcoord_type not in used_texcoords:
                used_texcoords.append(mask.texcoord_type)

    # Check for unused texcoords
    unused_texcoords = []
    for tc in texcoord_lists:
        if tc not in used_texcoords:
            unused_texcoords.append(tc)

    # Check parallax preparation nodes
    check_parallax_prep_nodes(mp, unused_uvs, unused_texcoords, baked=mp.use_baked)

    if height_ch:

        # Check standard parallax
        check_parallax_node(mp, height_ch, unused_uvs, unused_texcoords)

        # Check baked parallax
        check_parallax_node(mp, height_ch, unused_uvs, baked=True)

        # Update max height to parallax nodes
        update_displacement_height_ratio(height_ch)

    # Remove unused uv objects
    for i in unused_ids:
        uv = mp.uvs[i]
        remove_uv_nodes(uv, obj)
        dirty = True
        mp.uvs.remove(i)

    # Check actual uv nodes
    for uv in mp.uvs:
        check_actual_uv_nodes(mp, uv, obj)

    # Generate missing uvs for some objects
    if generate_missings:

        objs = []
        if obj.type == "MESH":
            objs.append(obj)

        if mat.users > 1:
            for ob in get_scene_objects():
                if ob.type != "MESH":
                    continue
                if mat.name in ob.data.materials and ob not in objs:
                    objs.append(ob)

        for ob in objs:
            uvls = get_uv_layers(ob)
            for uv in mp.uvs:
                if uv.name not in uvls:
                    uvl = uvls.new(name=uv.name)
                    uvls.active = uvl

    return dirty

