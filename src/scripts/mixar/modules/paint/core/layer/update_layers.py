# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ...utils.blender_commons import get_bpy_data, get_unique_name
from ..element.update_vcol import change_vcol_name
from ..node.create_nodes import new_node
from ..node.get_nodes import get_mask_source


def change_layer_name(mp, obj, src, layer, texes):
    """Update layer name and propagate changes to related resources.

    Changes the layer's name and ensures uniqueness among similar resources.
    Also updates related resources like vertex colors, images, and node group
    labels. Additionally updates mask names that reference the layer name.

    Parameters:
        mp: The MPaint main data structure.
        obj: The Blender object associated with the layer.
        src: The source node for the layer (e.g., image or vertex color node).
        layer: The layer object whose name is being changed.
        texes: Collection of texture resources to ensure name uniqueness.

    Returns:
        None
    """
    if mp.halt_update: return

    mp.halt_update = True

    if layer.type == 'VCOL' and obj.type == 'MESH':

        change_vcol_name(mp, obj, src, layer.name, layer)
        
    elif layer.type == 'IMAGE':
        # Check if src has an image (might be None for newly created layers)
        if src and hasattr(src, 'image') and src.image:
            src.image.name = '___TEMP___'
            layer.name = get_unique_name(layer.name, get_bpy_data().images)
            src.image.name = layer.name
        else:
            # No image node yet, just ensure unique name
            layer.name = get_unique_name(layer.name, get_bpy_data().images)

    else:
        name = layer.name
        layer.name = '___TEMP___'
        layer.name = get_unique_name(name, texes) 

    m1 = re.match(r'^mp\.layers\[(\d+)\]$', layer.path_from_id())
    m2 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', layer.path_from_id())
    if m1:
        group_tree = mp.id_data

        # Update node group label
        layer_group = group_tree.nodes.get(layer.group_node)
        layer_group.label = layer.name

        # Also update mask name if it's in certain pattern
        for mask in layer.masks:
            m = re.match(r'^Mask\s.*\((.+)\)$', mask.name)
            if m:
                old_layer_name = m.group(1)
                new_mask_name = mask.name.replace(old_layer_name, layer.name)
                if mask.type == 'IMAGE':
                    msrc = get_mask_source(mask)
                    if msrc.image and not msrc.image.yia.is_image_atlas and not msrc.image.yua.is_udim_atlas: 
                        msrc.image.name = '___TEMP___'
                        msrc.image.name = get_unique_name(new_mask_name, get_bpy_data().images) 
                elif mask.type == 'VCOL':
                    msrc = get_mask_source(mask)
                    mask.name = '___TEMP___'
                    change_vcol_name(mp, obj, msrc, new_mask_name, mask)
                else:
                    mask.name = new_mask_name

    mp.halt_update = False

def refresh_parallax_depth_source_layers(mp, parallax): #, disp_ch):
    """Refresh depth source layer nodes for parallax mapping.

    Updates or creates depth group nodes for all layers in the parallax
    depth source tree. Ensures each layer has a corresponding depth group
    node with the correct node tree reference.

    Parameters:
        mp: The MPaint main data structure.
        parallax: The parallax node containing the depth source configuration.

    Returns:
        None
    """
    depth_source_0 = parallax.node_tree.nodes.get('_depth_source_0')
    tree = depth_source_0.node_tree

    for layer in mp.layers:
        node = tree.nodes.get(layer.depth_group_node)
        if not node:
            n = mp.id_data.nodes.get(layer.group_node)
            node = new_node(tree, layer, 'depth_group_node', 'ShaderNodeGroup', layer.name)
            node.node_tree = n.node_tree