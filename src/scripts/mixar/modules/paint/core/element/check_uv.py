# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ..element.check_processes import is_tangent_process_needed
from ..layer.check_layers import get_layer_enabled, get_mask_enabled
from ..lib.lib import TANGENT_PROCESS_300
from ..lib.lib_operations import duplicate_lib_node_tree
from ..node.node_utils import get_node_tree_lib, remove_node
from ..node.create_nodes import new_node

def is_uv_input_needed(layer, uv_name):
    """
    Check if a UV input is needed for a layer.

    Determines if the specified UV map is required by the layer or any of its
    channels and masks based on their texture coordinate settings and bake status.

    Parameters:
        layer: Layer object to check
        uv_name (str): Name of the UV map to check

    Returns:
        bool: True if UV input is needed, False otherwise
    """
    mp = layer.id_data.mp

    if get_layer_enabled(layer):

        if layer.baked_source != '' and layer.use_baked and layer.baked_uv_name == uv_name:
            return True

        if layer.texcoord_type == 'UV' and layer.uv_name == uv_name:
            return True

        if layer.texcoord_type == 'UV' and layer.uv_name == uv_name:
            if layer.type not in {'VCOL', 'BACKGROUND', 'COLOR', 'GROUP', 'HEMI', 'EDGE_DETECT', 'AO'}:
                return True

            for i, ch in enumerate(layer.channels):
                if not ch.enable: continue
                root_ch = mp.channels[i]
                if root_ch.type != 'NORMAL':
                    if ch.override and ch.override_type not in {'DEFAULT', 'VCOL'}:
                        return True
                else:
                    if ch.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'} and ch.override and ch.override_type not in {'DEFAULT', 'VCOL'}:
                        return True

                    if ch.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'} and ch.override_1 and ch.override_1_type != 'DEFAULT':
                        return True
        
        for mask in layer.masks:
            if not get_mask_enabled(mask): continue
            if mask.use_baked and mask.baked_source != '' and mask.baked_uv_name == uv_name:
                return True
            if mask.type in {'VCOL', 'HEMI', 'OBJECT_INDEX', 'COLOR_ID', 'BACKFACE', 'EDGE_DETECT', 'AO'}: continue
            if (not mask.use_baked or mask.baked_source == '') and mask.texcoord_type == 'UV' and mask.uv_name == uv_name:
                return True

    return False

def is_any_entity_using_uv(mp, uv_name):
    """
    Check if any entity in the paint system uses a specific UV map.

    Scans all layers to determine if any entity (layer, channel, or mask) uses
    the specified UV map, including baked UV maps.

    Parameters:
        mp: MPaint node tree data
        uv_name (str): Name of the UV map to check

    Returns:
        bool: True if UV map is in use, False otherwise
    """
    if mp.baked_uv_name != '' and mp.baked_uv_name == uv_name:
        return True

    for layer in mp.layers:
        if is_uv_input_needed(layer, uv_name):
            return True

    return False

def check_actual_uv_nodes(mp, uv, obj):
    """
    Check and update UV map nodes and tangent process nodes.

    Creates or removes UV map nodes and tangent process nodes based on whether
    the UV is being used by any entity and if tangent processing is needed.

    Parameters:
        mp: MPaint node tree data
        uv: UV layer object
        obj: Blender object containing the UV map

    Returns:
        None
    """
    tree = mp.id_data

    if is_any_entity_using_uv(mp, uv.name):
        uv_map = tree.nodes.get(uv.uv_map)
        if not uv_map:
            uv_map = new_node(tree, uv, 'uv_map', 'ShaderNodeUVMap', uv.name)
            uv_map.uv_map = uv.name
    else:
        remove_node(tree, uv, 'uv_map')

    if is_tangent_process_needed(mp, uv.name):
        tangent_process = tree.nodes.get(uv.tangent_process)

        if not tangent_process:
            # Create tangent process which output both tangent and bitangent
            tangent_process = new_node(tree, uv, 'tangent_process', 'ShaderNodeGroup', uv.name + ' Tangent Process')
            tangent_process.node_tree = get_node_tree_lib(TANGENT_PROCESS_300)
            duplicate_lib_node_tree(tangent_process)

            tangent_process.inputs['Backface Always Up'].default_value = 1.0 if mp.enable_backface_always_up else 0.0

            # Set values inside tangent process
            tp_nodes = tangent_process.node_tree.nodes
            node = tp_nodes.get('_tangent')
            if node: node.uv_map = uv.name
            node = tp_nodes.get('_tangent_from_norm')
            if node: node.uv_map = uv.name
            node = tp_nodes.get('_bitangent_from_norm')
            if node: node.uv_map = uv.name
    else:
        remove_node(tree, uv, 'tangent_process')
