# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ..lib.lib import BUMP_PROCESS, FINE_BUMP_PROCESS, SUBDIV_ON_NORMAL
from ..node.node_utils import remove_node, is_normal_height_input_connected
from ..subtree.get_subtree import get_tree
from ...utils.blender_commons import get_user_preferences
from ..node.create_nodes import replace_new_node

from ..layer.check_layers import any_layers_using_bump_map, check_need_prev_normal, get_channel_enabled, get_layer_enabled, get_mask_enabled, is_layer_using_normal_map
from ..layer.layer_utils import get_height_channel, get_root_height_channel
from ...utils.common import is_parallax_enabled


def is_tangent_process_needed(mp, uv_name):
    """
    Check if tangent process is needed for a UV map.

    Determines if tangent/bitangent processing is required for the specified UV
    map based on height channel settings and bump mapping configuration.

    Parameters:
        mp: MPaint node tree data
        uv_name (str): Name of the UV map to check

    Returns:
        bool: True if tangent process is needed, False otherwise
    """
    height_root_ch = get_root_height_channel(mp)
    if height_root_ch:

        if height_root_ch.main_uv == uv_name and (
                (height_root_ch.enable_smooth_bump and any_layers_using_bump_map(height_root_ch)) or
                (is_normal_height_input_connected(height_root_ch) and height_root_ch.enable_smooth_bump)
            ):
            return True

        for layer in mp.layers:
            if is_tangent_input_needed(layer, uv_name):
                return True

    return False

def is_entity_need_tangent_input(entity, uv_name):
    """
    Check if an entity needs tangent input for a specific UV map.

    Determines if tangent data is required for the entity based on its type,
    height channel configuration, and UV mapping settings.

    Parameters:
        entity: Layer or mask entity to check
        uv_name (str): Name of the UV map to check

    Returns:
        bool: True if tangent input is needed, False otherwise
    """
    mp = entity.id_data.mp

    m = re.match(r'mp\.layers\[(\d+)\]\.masks\[(\d+)\]', entity.path_from_id())
    if m: 
        layer = mp.layers[int(m.group(1))]
        entity_enabled = get_mask_enabled(entity)
        is_mask = True
    else: 
        layer = entity
        entity_enabled = get_layer_enabled(entity)
        is_mask = False

    if entity_enabled and (entity.use_baked or entity.type not in {'BACKGROUND', 'COLOR', 'OBJECT_INDEX', 'COLOR_ID', 'BACKFACE'}):

        height_root_ch = get_root_height_channel(mp)
        height_ch = get_height_channel(layer)

        # Previous normal is calculated using normal process
        if height_root_ch and height_root_ch.enable_smooth_bump and check_need_prev_normal(layer):
            return True

        if height_root_ch and height_ch and get_channel_enabled(height_ch, layer, height_root_ch):

            if entity.type == 'GROUP':

                if is_layer_using_normal_map(entity, height_root_ch):
                    return True

            elif uv_name == height_root_ch.main_uv:

                # Main UV tangent is needed for normal process
                if is_parallax_enabled(height_root_ch) and height_ch.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'} or mp.layer_preview_mode or not height_ch.write_height:
                    return True

                # Overlay blend and transition bump need tangent
                if height_ch.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'} and (height_ch.normal_blend_type == 'OVERLAY' or (height_ch.enable_transition_bump and height_root_ch.enable_smooth_bump)):
                    return True

                # Main UV Tangent is needed if smooth bump is on and entity is using non-uv texcoord or have different UV
                if height_root_ch.enable_smooth_bump and (entity.texcoord_type != 'UV' or entity.uv_name != uv_name) and height_ch.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
                    return True

                # Fake neighbor need tangent
                if height_root_ch.enable_smooth_bump and entity.type in {'VCOL', 'HEMI', 'EDGE_DETECT', 'AO'} and not entity.use_baked:
                    return True

            elif entity.uv_name == uv_name and entity.texcoord_type == 'UV':

                # Entity UV tangent is needed if smooth bump is on and entity is using different UV than main UV
                if height_root_ch.enable_smooth_bump and height_root_ch.main_uv != uv_name and height_ch.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
                    return True

    return False

def is_tangent_input_needed(layer, uv_name):
    """
    Check if tangent input is needed for a layer or any of its masks.

    Scans the layer and all its masks to determine if tangent data is required
    for the specified UV map.

    Parameters:
        layer: Layer object to check
        uv_name (str): Name of the UV map to check

    Returns:
        bool: True if tangent input is needed, False otherwise
    """
    if is_entity_need_tangent_input(layer, uv_name):
        return True

    for mask in layer.masks:
        if is_entity_need_tangent_input(mask, uv_name):
            return True

    return False

def check_layer_bump_process(layer, tree=None):
    """
    Check and update bump process node for a layer.

    Creates or removes bump process nodes based on whether the layer needs
    previous normal calculations for height/bump mapping. Selects appropriate
    process type (subdiv, fine bump, or standard bump) based on settings.

    Parameters:
        layer: Layer object to check
        tree: Node tree to operate on (default: None, uses layer tree)

    Returns:
        bool: True if changes were made (dirty), False otherwise
    """
    mpup = get_user_preferences()
    mp = layer.id_data.mp
    if not tree: tree = get_tree(layer)

    height_root_ch = get_root_height_channel(mp)

    # Check if previous normal is needed
    need_prev_normal = check_need_prev_normal(layer)

    dirty = False

    if need_prev_normal and get_layer_enabled(layer):
        if height_root_ch.enable_subdiv_setup: # and mpup.eevee_next_displacement:
            lib_name = SUBDIV_ON_NORMAL
        elif height_root_ch.enable_smooth_bump:
            lib_name = FINE_BUMP_PROCESS
        else: lib_name = BUMP_PROCESS

        bump_process, dirty = replace_new_node(
            tree, layer, 'bump_process', 'ShaderNodeGroup', 'Bump Process',
            lib_name, return_status=True, hard_replace=True
        )

        #update_layer_bump_process_max_height(height_root_ch, layer, tree)
    else:
        dirty = remove_node(tree, layer, 'bump_process')

    return dirty
