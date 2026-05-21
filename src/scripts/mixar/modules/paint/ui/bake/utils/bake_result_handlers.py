# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Result handling functions for entity baking - atlas, layers, masks, overrides, and info storage."""

import bpy

from ....core.element.update_image import copy_image_pixels
from ....core.element.update_uv import refresh_temp_uv, set_uv_neighbor_resolution
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes
from ....utils.blender_commons import (
    get_active_object,
    get_srgb_name,
    get_unique_name,
    remove_datablock,
    safe_remove_image,
)

from ...image_atlas.image_atlas_utils import (
    check_need_of_erasing_segments,
    clear_unused_segments,
    get_set_image_atlas_segment,
    set_segment_mapping,
)
from ...mask.mask_creation import add_new_mask
from ...udim.udim_utils_atlas import get_set_udim_atlas_segment, get_udim_segment_mapping_offset, copy_tiles
from ...udim.udim_utils_segment import remove_udim_atlas_segment_by_name


def handle_image_atlas(image, bprops, segment, tilenums, mp):
    """Handle image atlas operations.

    Parameters:
        image: Baked image
        bprops: Bake properties
        segment: Existing segment if any
        tilenums: List of UDIM tile numbers
        mp: Material properties

    Returns:
        tuple: (image, segment, new_segment_created)
    """
    if not bprops.use_image_atlas:
        return image, segment, False

    need_to_create_new_segment = False
    if segment:
        ia_image = segment.id_data
        if bprops.use_udim:
            need_to_create_new_segment = ia_image.is_float != bprops.hdr
            if need_to_create_new_segment:
                remove_udim_atlas_segment_by_name(ia_image, segment.name, mp)
        else:
            need_to_create_new_segment = (
                bprops.width != segment.width
                or bprops.height != segment.height
                or ia_image.is_float != bprops.hdr
            )
            if need_to_create_new_segment:
                segment.unused = True

    if not segment or need_to_create_new_segment:
        if bprops.use_udim:
            segment = get_set_udim_atlas_segment(
                tilenums,
                color=(0, 0, 0, 0),
                colorspace=get_srgb_name(),
                hdr=bprops.hdr,
                mp=mp,
            )
        else:
            img_atlas = check_need_of_erasing_segments(
                mp, "TRANSPARENT", bprops.width, bprops.height, bprops.hdr
            )
            if img_atlas:
                clear_unused_segments(img_atlas.yia)

            segment = get_set_image_atlas_segment(
                bprops.width, bprops.height, "TRANSPARENT", bprops.hdr, mp=mp
            )

        new_segment_created = True
    else:
        new_segment_created = False

    ia_image = segment.id_data

    # Set baked image to segment
    if bprops.use_udim:
        offset = get_udim_segment_mapping_offset(segment) * 10
        copy_dict = {}
        for tilenum in tilenums:
            copy_dict[tilenum] = tilenum + offset
        copy_tiles(image, ia_image, copy_dict)
    else:
        copy_image_pixels(image, ia_image, segment)

    temp_img = image
    image = ia_image

    # Remove original baked image
    remove_datablock(bpy.data.images, temp_img)

    return image, segment, new_segment_created


def create_layer_from_bake(mp, node, bprops, image, segment, channel_idx):
    """Create a new layer from baked image.

    Parameters:
        mp: Material properties
        node: mPaint node
        bprops: Bake properties
        image: Baked image
        segment: Image segment if using atlas
        channel_idx: Channel index

    Returns:
        int: Active layer index
    """
    from ...layer.helpers.layer_create_helpers import add_new_layer

    layer_name = image.name if not bprops.use_image_atlas else bprops.name

    if bprops.use_image_atlas:
        layer_name = get_unique_name(layer_name, mp.layers)

    mp.halt_update = True
    layer = add_new_layer(
        group_tree=node.node_tree,
        layer_name=layer_name,
        layer_type="IMAGE",
        channel_idx=channel_idx,
        blend_type=bprops.blend_type,
        normal_blend_type=bprops.normal_blend_type,
        normal_map_type=bprops["normal_map_type"],
        texcoord_type="UV",
        uv_name=bprops.uv_map,
        image=image,
        vcol=None,
        segment=segment,
        interpolation=bprops.interpolation,
        normal_space="OBJECT" if bprops.type == "OBJECT_SPACE_NORMAL" else "TANGENT",
    )
    mp.halt_update = False

    layer.enable = True
    active_id = mp.active_layer_index

    if segment:
        set_segment_mapping(layer, segment, image)

    refresh_temp_uv(get_active_object(), layer)
    set_uv_neighbor_resolution(layer)

    return active_id


def create_mask_from_bake(mp, bprops, image, segment):
    """Create a new mask from baked image.

    Parameters:
        mp: Material properties
        bprops: Bake properties
        image: Baked image
        segment: Image segment if using atlas

    Returns:
        int: Active layer index
    """
    active_layer = mp.layers[mp.active_layer_index]

    mask_name = image.name if not bprops.use_image_atlas else bprops.name

    if bprops.use_image_atlas:
        mask_name = get_unique_name(mask_name, active_layer.masks)

    mask = add_new_mask(
        active_layer,
        mask_name,
        "IMAGE",
        "UV",
        bprops.uv_map,
        image,
        "",
        segment,
    )
    mask.active_edit = True

    reconnect_layer_nodes(active_layer)
    rearrange_layer_nodes(active_layer)

    active_id = mp.active_layer_index

    if segment:
        set_segment_mapping(mask, segment, image)

    refresh_temp_uv(get_active_object(), mask)
    set_uv_neighbor_resolution(mask)

    return active_id


def update_channel_override(mp, bprops, image, idx):
    """Update layer with baked image.

    For Fill layers (COLOR type): Set channel's override_type to IMAGE
    For other layers: Update layer source directly

    Parameters:
        mp: Material properties
        bprops: Bake properties
        image: Baked image
        idx: Channel index
    """
    from ....core.subtree.get_subtree import get_tree
    from ....core.node.get_nodes import get_layer_source

    layer = mp.layers[mp.active_layer_index]
    ch = layer.channels[idx]

    if not ch.enable:
        ch.enable = True

    layer_tree = get_tree(layer)

    # For Fill layers (COLOR type), use channel's IMAGE override
    if layer.type == 'COLOR':
        # Set override_type to IMAGE - this creates the channel's image source node
        ch.override_type = 'IMAGE'

        # Get the channel's override source node (created by override_type callback)
        source = layer_tree.nodes.get(ch.source)
        if source and hasattr(source, 'image'):
            source.image = image
            if hasattr(source, 'interpolation'):
                source.interpolation = bprops.interpolation

        # Reconnect and rearrange nodes
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)
    else:
        # For other layer types, update layer source directly
        source = get_layer_source(layer, layer_tree)

        if source and hasattr(source, 'image'):
            old_image = None
            if source.image and image != source.image:
                old_image = source.image
                source_name = old_image.name
                current_name = image.name
                old_image.name = "_____temp"
                image.name = source_name
                old_image.name = current_name

            source.image = image
            if hasattr(source, 'interpolation'):
                source.interpolation = bprops.interpolation

            if old_image:
                safe_remove_image(old_image)


def store_bake_info(image, segment, bprops, other_objs, fill_mode, obj_vertex_indices):
    """Store bake information in image/segment.

    Parameters:
        image: Baked image
        segment: Image segment if using atlas
        bprops: Bake properties
        other_objs: List of other objects used in bake
        fill_mode: Fill mode for selected vertices
        obj_vertex_indices: Dictionary of object vertex indices
    """
    bi = segment.bake_info if segment else image.m_bake_info

    if not bi.is_baked:
        bi.is_baked = True
    if bi.bake_type != bprops.type:
        bi.bake_type = bprops.type

    for attr in dir(bi):
        if attr.startswith("__") or attr.startswith("bl_") or attr in {"rna_type"}:
            continue
        try:
            setattr(bi, attr, bprops[attr])
        except:
            pass

    if other_objs:
        for o in other_objs:
            oo_recorded = any([oo for oo in bi.other_objects if oo.object == o])
            if not oo_recorded:
                oo = bi.other_objects.add()
                oo.object = o
                oo.object_name = o.name

        for i, oo in reversed(list(enumerate(bi.other_objects))):
            ooo = oo.object
            if ooo not in other_objs:
                bi.other_objects.remove(i)

    if bprops.type == "SELECTED_VERTICES":
        bi.selected_face_mode = True if fill_mode == "FACE" else False
        bi.selected_objects.clear()

        for obj_name, v_indices in obj_vertex_indices.items():
            ob = bpy.data.objects.get(obj_name)
            bso = bi.selected_objects.add()
            bso.object = ob
            bso.object_name = ob.name

            for vi in v_indices:
                bvi = bso.selected_vertex_indices.add()
                bvi.index = vi
