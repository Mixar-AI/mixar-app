# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer type helpers: functions for replacing layer types."""

import bpy

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.element.update_uv import set_uv_neighbor_resolution
from ....core.element.update_vcol import set_active_vertex_color_by_name
from ....core.io.input_outputs.input_outputs import check_layer_channel_linear_node
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.layer.get_entities import any_single_user_ondisk_image_inside_group
from ....core.layer.layer_utils import get_height_channel, get_layer_index_by_name
from ....core.layer.mappings import clear_mapping
from ....core.lib.lib import HEMI
from ....core.lib.lib_operations import duplicate_lib_node_tree
from ....core.modifier.modifier import check_modifiers_trees
from ....core.node.check_nodes import check_all_layer_channel_io_and_nodes, check_uv_nodes
from ....core.node.create_nodes import new_node
from ....core.node.get_nodes import get_layer_source
from ....core.node.node_utils import get_node_tree_lib, remove_node
from ....core.subtree.get_subtree import (
    get_list_of_direct_child_ids,
    get_parent_dict,
    get_source_tree,
    get_tree,
)
from ....procedural_materials.material_registry import get_node_group, is_custom_material
from ....utils.blender_commons import (
    enable_eevee_ao,
    get_active_material,
    get_active_object,
    get_unique_name,
)
from ....utils.common import load_hemi_props, save_hemi_props, set_source_vcol_name
from ....utils.constants import layer_node_bl_idnames, layer_type_labels
from ...image_atlas.image_atlas_utils import set_segment_mapping
from ...mask.mask_operators_helper import setup_edge_detect_source
from ...udim.udim_utils import remove_udim_atlas_segment_by_name, set_udim_segment_mapping
from .layer_enum_helpers import DEFAULT_NEW_IMG_SUFFIX


def replace_layer_type(layer, new_type, item_name="", remove_data=False):
    """Replace the type of an existing layer with a new type.

    Args:
        layer: YLayer object to modify.
        new_type (str): New layer type to set.
        item_name (str, optional): Name of item associated with new type. Defaults to "".
        remove_data (bool, optional): Whether to remove old data. Defaults to False.
    """

    mp = layer.id_data.mp

    # Remember parents
    parent_dict = get_parent_dict(mp)
    child_ids = []

    # If layer type is group, get children and repoint child parents
    if layer.type == "GROUP":
        # Get children and repoint child parents
        child_ids = get_list_of_direct_child_ids(layer)
        for i in child_ids:
            parent_dict[mp.layers[i].name] = parent_dict[layer.name]

    # Check if layer is using image atlas
    if layer.type == "IMAGE" and layer.segment_name != "":

        # Replace to non atlas image will remove the segment
        if new_type == "IMAGE":
            src = get_layer_source(layer)
            if src.image.yia.is_image_atlas:
                segment = src.image.yia.segments.get(layer.segment_name)
                segment.unused = True
            elif src.image.yua.is_udim_atlas:
                remove_udim_atlas_segment_by_name(src.image, layer.segment_name, mp=mp)

            # Set segment name to empty
            layer.segment_name = ""

        # Reset mapping
        clear_mapping(layer)

    # Save hemi vector
    if layer.type == "HEMI":
        src = get_layer_source(layer)
        save_hemi_props(layer, src)

    mp.halt_reconnect = True

    fine_bump_channels = [ch for ch in mp.channels if ch.enable_smooth_bump]
    for ch in fine_bump_channels:
        ch.enable_smooth_bump = False

    # Disable transition will also helps
    transition_channels = [ch for ch in layer.channels if ch.enable_transition_bump]
    for ch in transition_channels:
        ch.enable_transition_bump = False

    # Current source
    tree = get_tree(layer)
    source_tree = get_source_tree(layer)
    source = source_tree.nodes.get(layer.source)

    # Determine actual layer type for comparison (PROCEDURAL for custom materials)
    actual_new_type = "PROCEDURAL" if is_custom_material(new_type) else new_type

    # Save source to cache
    if (
        layer.type not in {"BACKGROUND", "GROUP", "HEMI", "EDGE_DETECT", "AO", "PROCEDURAL"}
        and layer.type != actual_new_type
    ):
        setattr(layer, "cache_" + layer.type.lower(), source.name)
        # Remove uv input link
        if any(source.inputs) and any(source.inputs[0].links):
            tree.links.remove(source.inputs[0].links[0])
        source.label = ""
    else:
        remove_node(source_tree, layer, "source", remove_data=remove_data)

    # Determine actual layer type (PROCEDURAL for custom materials)
    actual_layer_type = "PROCEDURAL" if is_custom_material(new_type) else new_type

    # Try to get available cache
    cache = None
    if actual_layer_type not in {
        "IMAGE",
        "VCOL",
        "BACKGROUND",
        "GROUP",
        "HEMI",
        "EDGE_DETECT",
        "AO",
        "PROCEDURAL",
    } or (actual_layer_type in {"IMAGE", "VCOL"} and item_name == ""):
        cache = tree.nodes.get(getattr(layer, "cache_" + actual_layer_type.lower()))

    if cache:
        layer.source = cache.name
        setattr(layer, "cache_" + new_type.lower(), "")
        cache.label = "Source"
    else:
        # Determine node type for source
        if is_custom_material(new_type):
            node_bl_idname = "ShaderNodeGroup"
        else:
            node_bl_idname = layer_node_bl_idnames[new_type]

        source = new_node(
            source_tree, layer, "source", node_bl_idname, "Source"
        )

        if new_type == "IMAGE":
            image = bpy.data.images.get(item_name)
            source.image = image

            if layer.texcoord_type == "Decal":
                source.extension = "CLIP"

        elif new_type == "VCOL":
            set_source_vcol_name(source, item_name)
        elif new_type == "HEMI":
            source.node_tree = get_node_tree_lib(HEMI)
            duplicate_lib_node_tree(source)

            load_hemi_props(layer, source)

        elif new_type == "EDGE_DETECT":
            setup_edge_detect_source(layer, source)

        elif new_type == "AO":
            enable_eevee_ao()

        # Handle custom procedural materials
        elif is_custom_material(new_type):
            node_group = get_node_group(new_type)
            if node_group:
                source.node_tree = node_group
                # Make a copy for this instance
                duplicate_lib_node_tree(source)
            else:
                error_msg = f"Failed to load procedural material: {new_type}. Node group not found."
                logger.error(error_msg)
                raise RuntimeError(error_msg)

    # Change layer type
    ori_type = layer.type
    if is_custom_material(new_type):
        # For custom materials, set type to PROCEDURAL and store the material ID
        layer.type = "PROCEDURAL"
        layer.procedural_material_id = new_type
    else:
        layer.type = new_type

    # Check modifiers tree
    check_modifiers_trees(layer)

    # Always remove baked layer when changing type
    if layer.use_baked:
        layer.use_baked = False
        remove_node(tree, layer, "baked_source")

    # Update group ios
    check_all_layer_channel_io_and_nodes(layer, tree)
    if layer.type == "BACKGROUND":
        # Remove bump and its base
        for ch in layer.channels:
            remove_node(tree, ch, "normal_process")

    # Update linear stuff
    for i, ch in enumerate(layer.channels):
        root_ch = mp.channels[i]
        check_layer_channel_linear_node(ch, layer, root_ch)

    # Back to use fine bump if conversion happen
    for ch in fine_bump_channels:
        ch.enable_smooth_bump = True

    # Bring back transition
    for ch in transition_channels:
        ch.enable_transition_bump = True

    # Update uv neighbor
    set_uv_neighbor_resolution(layer)

    mp.halt_reconnect = False

    # Remap parents
    for lay in mp.layers:
        lay.parent_idx = get_layer_index_by_name(mp, parent_dict[lay.name])

    # Check uv maps
    check_uv_nodes(mp)

    # Update layer name
    image = None
    if layer.type == "IMAGE":
        # Rename layer with image name
        source = get_layer_source(layer)
        if source and source.image:
            image = source.image
            mp.halt_update = True
            if image.yia.is_image_atlas or image.yua.is_udim_atlas:
                mat = get_active_material()
                new_name = mat.name if mat else "Image"
                new_name += DEFAULT_NEW_IMG_SUFFIX

                # Set back the mapping
                if image.yia.is_image_atlas:
                    segment = image.yia.segments.get(layer.segment_name)
                    set_segment_mapping(layer, segment, image)
                else:
                    segment = image.yua.segments.get(layer.segment_name)
                    set_udim_segment_mapping(layer, segment, image)

            else:
                new_name = image.name
            layer.name = get_unique_name(new_name, mp.layers)
            mp.halt_update = False

            # Set interpolation to Cubic if normal/height channel is found
            height_ch = get_height_channel(layer)
            if height_ch and height_ch.enable:
                source.interpolation = "Cubic"

    elif layer.type == "VCOL":
        # Rename layer with vcol name
        source = get_layer_source(layer)
        if source:
            layer.name = get_unique_name(source.attribute_name, mp.layers)

        # Set active vertex color
        set_active_vertex_color_by_name(get_active_object(), source.attribute_name)

    elif ori_type in {"IMAGE", "VCOL"}:
        # Rename layer with texture types
        layer.name = get_unique_name(layer_type_labels[layer.type], mp.layers)

    elif layer_type_labels[ori_type] in layer.name:
        # Rename texture types with another texture types
        layer.name = get_unique_name(
            layer.name.replace(
                layer_type_labels[ori_type], layer_type_labels[layer.type]
            ),
            mp.layers,
        )

    # Refresh colorspace
    for root_ch in mp.channels:
        if root_ch.type == "RGB":
            root_ch.colorspace = root_ch.colorspace

    # Check children which need rearrange
    for lay in mp.layers:
        check_all_layer_channel_io_and_nodes(lay)
        reconnect_layer_nodes(lay)
        rearrange_layer_nodes(lay)

    if layer.type in {"BACKGROUND", "GROUP"} or ori_type == "GROUP":
        reconnect_mp_nodes(layer.id_data)
        rearrange_mp_nodes(layer.id_data)

    # Update UI
    bpy.context.window_manager.mpui.need_update = True
    layer.expand_source = layer.type not in {"IMAGE", "VCOL"} or (
        image is not None
        and image.m_bake_info.is_baked
        and not image.m_bake_info.is_baked_channel
    )
