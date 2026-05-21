# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask type utility functions for naming, caching, and type replacement.

This module contains utilities for managing mask names, caching mask configurations,
and replacing mask types while preserving data.
"""

import re

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.check_elements import check_colorid_vcol
from ...core.element.get_elements import get_default_uv_name, get_vertex_color_names
from ...core.element.update_vcol import set_active_vertex_color_by_name
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.layer.layer_utils import get_height_channel
from ...core.layer.mappings import clear_mapping, is_mapping_possible
from ...core.lib.lib import HEMI
from ...core.lib.lib_operations import duplicate_lib_node_tree
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...core.modifier.mask_modifier import mask_modifier_type_labels
from ...core.node.check_nodes import check_all_layer_channel_io_and_nodes, check_uv_nodes
from ...core.node.create_nodes import new_node
from ...core.node.get_nodes import get_mask_source
from ...core.node.node_utils import get_node_tree_lib, remove_node
from ...core.subtree.get_subtree import get_mask_tree
from ...utils.blender_commons import (
    enable_eevee_ao,
    get_active_material,
    get_active_object,
    get_noncolor_name,
    get_unique_name,
    get_user_preferences,
)
from ...utils.common import (
    load_hemi_props,
    save_hemi_props,
    set_source_vcol_name,
)
from ...utils.constants import layer_node_bl_idnames, mask_type_items, mask_type_labels
from ..image_atlas.image_atlas_utils import set_segment_mapping
from ..udim.udim_utils import is_uvmap_udim, remove_udim_atlas_segment_by_name, set_udim_segment_mapping
from .mask_source_setup import (
    setup_color_id_source,
    setup_edge_detect_source,
    setup_modifier_mask_source,
    setup_object_idx_source,
)


def get_new_mask_name(obj, layer, mask_type, modifier_type=''):
    """Generate a unique name for a new mask based on its type.

    Args:
        obj: Blender object that owns the material.
        layer: YLayer property group to add the mask to.
        mask_type (str): Type of mask (IMAGE, VCOL, MODIFIER, etc.).
        modifier_type (str, optional): Modifier type if mask_type is MODIFIER. Defaults to ''.

    Returns:
        str: Unique mask name with layer name suffix in format "Mask Type (Layer Name)".
    """
    surname = '(' + layer.name + ')'
    items = layer.masks
    if mask_type == 'IMAGE':
        name = 'Mask'
        name = get_unique_name(name, layer.masks, surname)
        name = get_unique_name(name, bpy.data.images)
        return name
    elif mask_type == 'VCOL' and obj.type == 'MESH':
        name = 'Mask VCol'
        items = get_vertex_color_names(obj)
        return get_unique_name(name, items, surname)
    elif mask_type == 'MODIFIER':
        name = 'Mask ' + modifier_type.title()
        return get_unique_name(name, items, surname)
    else:
        name = 'Mask ' + [i[1] for i in mask_type_items if i[0] == mask_type][0]
        return get_unique_name(name, items, surname)


def update_new_mask_uv_map(self, context):
    """Update callback for new mask UV map selection with automatic UDIM detection.

    Args:
        self: Operator instance with type and uv_name properties.
        context: Blender context object.
    """
    if self.type != 'IMAGE':
        self.use_udim = False
        return

    if get_user_preferences().enable_auto_udim_detection:
        mat = get_active_material()
        objs = get_all_objects_with_same_materials(mat)
        self.use_udim = is_uvmap_udim(objs, self.uv_name)


def get_mask_cache_name(mask_type, modifier_type=''):
    """Generate the cache property name for a mask type.

    Args:
        mask_type (str): Type of mask (IMAGE, VCOL, MODIFIER, etc.).
        modifier_type (str, optional): Modifier type if mask_type is MODIFIER. Defaults to ''.

    Returns:
        str: Cache property name in format "cache_masktype" or "cache_modifier_modifiertype".
    """
    name = 'cache_' + mask_type.lower()

    if mask_type == 'MODIFIER':
        name += '_' + modifier_type.lower()

    return name


def is_mask_type_cacheable(mask_type, modifier_type=''):
    """Check if a mask type can be cached for reuse when switching types.

    Args:
        mask_type (str): Type of mask to check.
        modifier_type (str, optional): Modifier type if mask_type is MODIFIER. Defaults to ''.

    Returns:
        bool: True if the mask type can be cached, False otherwise.
    """
    if mask_type == 'MODIFIER':
        return modifier_type in {'RAMP', 'CURVE'}

    return mask_type not in {'HEMI', 'OBJECT_INDEX', 'COLOR_ID', 'EDGE_DETECT', 'BACKFACE', 'AO'}


def _handle_atlas_segment_on_replace(mask, new_type, mp):
    """Handle image atlas segment cleanup when replacing mask type.

    Args:
        mask: YLayerMask property group being modified.
        new_type (str): New mask type to change to.
        mp: Material properties group.
    """
    if mask.type != 'IMAGE' or mask.segment_name == '':
        return

    # Replace to non atlas image will remove the segment
    if new_type == 'IMAGE':
        src = get_mask_source(mask)
        if src.image.yia.is_image_atlas:
            segment = src.image.yia.segments.get(mask.segment_name)
            segment.unused = True
        elif src.image.yua.is_udim_atlas:
            remove_udim_atlas_segment_by_name(src.image, mask.segment_name, mp=mp)

        # Set segment name to empty
        mask.segment_name = ''

    # Reset mapping
    clear_mapping(mask)


def _save_current_source_to_cache(mask, tree, source, remove_data=False):
    """Save current mask source to cache or remove it.

    Args:
        mask: YLayerMask property group.
        tree: Shader node tree.
        source: Current source node.
        remove_data (bool): Whether to remove old data blocks.
    """
    if is_mask_type_cacheable(mask.type, mask.modifier_type):
        setattr(mask, get_mask_cache_name(mask.type, mask.modifier_type), source.name)
        # Remove uv input link
        if any(source.inputs) and any(source.inputs[0].links):
            tree.links.remove(source.inputs[0].links[0])
        source.label = ''
    else:
        # Remember values by disabling then enabling the mask again
        if mask.enable:
            mask.enable = False
            mask.enable = True

        remove_node(tree, mask, 'source', remove_data=remove_data)


def _create_new_source_from_cache_or_new(mask, tree, new_type, item_name, modifier_type):
    """Create new source node from cache or create fresh.

    Args:
        mask: YLayerMask property group.
        tree: Shader node tree.
        new_type (str): New mask type.
        item_name (str): Name of image or vertex color.
        modifier_type (str): Modifier type if applicable.

    Returns:
        The source node (from cache or newly created).
    """
    # Try to get available cache
    cache = None
    if is_mask_type_cacheable(new_type, modifier_type) and mask.type != new_type:
        cache = tree.nodes.get(getattr(mask, get_mask_cache_name(new_type, modifier_type)))

    if cache:
        mask.source = cache.name
        setattr(mask, get_mask_cache_name(new_type, modifier_type), '')
        cache.label = 'Source'
        return cache

    source = None
    if new_type == 'MODIFIER':
        source = setup_modifier_mask_source(tree, mask, modifier_type)
    elif new_type != 'BACKFACE':
        source = new_node(tree, mask, 'source', layer_node_bl_idnames[new_type], 'Source')

    if new_type == 'IMAGE':
        image = bpy.data.images.get(item_name)
        source.image = image

        if mask.texcoord_type == 'Decal':
            source.extension = 'CLIP'

        if hasattr(source, 'color_space'):
            source.color_space = 'NONE'
        if image.colorspace_settings.name != get_noncolor_name() and not image.is_dirty:
            image.colorspace_settings.name = get_noncolor_name()

    elif new_type == 'VCOL':
        set_source_vcol_name(source, item_name)

    elif new_type == 'HEMI':
        source.node_tree = get_node_tree_lib(HEMI)
        duplicate_lib_node_tree(source)
        load_hemi_props(mask, source)

    elif new_type == 'COLOR_ID':
        mat = get_active_material()
        objs = get_all_objects_with_same_materials(mat)
        check_colorid_vcol(objs, set_as_active=True)
        setup_color_id_source(mask, source)

    elif new_type == 'OBJECT_INDEX':
        setup_object_idx_source(mask, source)

    elif new_type == 'EDGE_DETECT':
        setup_edge_detect_source(mask, source)

    elif new_type == 'AO':
        enable_eevee_ao()

    return source


def _update_mask_name_after_replace(mask, layer, mp, ori_type):
    """Update mask name after type replacement.

    Args:
        mask: YLayerMask property group.
        layer: YLayer property group.
        mp: Material properties group.
        ori_type (str): Original mask type before replacement.

    Returns:
        Image object if mask type is IMAGE, else None.
    """
    image = None
    if mask.type == 'IMAGE':
        # Rename mask with image name
        source = get_mask_source(mask)
        if source and source.image:
            image = source.image
            mp.halt_update = True
            if image.yia.is_image_atlas or image.yua.is_udim_atlas:
                new_name = 'Mask (' + layer.name + ')'

                # Set back the mapping
                if image.yia.is_image_atlas:
                    segment = image.yia.segments.get(mask.segment_name)
                    set_segment_mapping(mask, segment, image)
                else:
                    segment = image.yua.segments.get(mask.segment_name)
                    set_udim_segment_mapping(mask, segment, image)

            else:
                new_name = image.name
            mask.name = get_unique_name(new_name, layer.masks)
            mp.halt_update = False

            # Set interpolation to Cubic if normal/height channel is found
            height_ch = get_height_channel(mask)
            if height_ch and height_ch.enable:
                source.interpolation = 'Cubic'

    elif mask.type == 'VCOL':
        # Rename mask with vcol name
        source = get_mask_source(mask)
        if source:
            mask.name = get_unique_name(source.attribute_name, layer.masks)

        # Set active vertex color
        set_active_vertex_color_by_name(get_active_object(), source.attribute_name)

    elif mask.type == 'MODIFIER':
        # Rename mask with modifier types
        mask.name = get_unique_name(mask_modifier_type_labels[mask.modifier_type], layer.masks)

    elif ori_type in {'IMAGE', 'VCOL'}:
        # Rename mask with texture types
        mask.name = get_unique_name(mask_type_labels[mask.type], layer.masks)

    elif mask_type_labels[ori_type] in mask.name:
        # Rename texture types with another texture types
        mask.name = get_unique_name(
            mask.name.replace(mask_type_labels[ori_type], mask_type_labels[mask.type]),
            layer.masks
        )

    return image


def replace_mask_type(mask, new_type, item_name='', remove_data=False, modifier_type='INVERT'):
    """Replace the type of an existing mask while preserving as much data as possible.

    Args:
        mask: YLayerMask property group to modify.
        new_type (str): New mask type to change to (IMAGE, VCOL, MODIFIER, etc.).
        item_name (str, optional): Name of image or vertex color for the new type. Defaults to ''.
        remove_data (bool, optional): Whether to remove old data blocks. Defaults to False.
        modifier_type (str, optional): Modifier type if new_type is MODIFIER. Defaults to 'INVERT'.
    """
    mp = mask.id_data.mp

    match = re.match(r'mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', mask.path_from_id())
    layer = mp.layers[int(match.group(1))]

    # Handle atlas segment cleanup
    _handle_atlas_segment_on_replace(mask, new_type, mp)

    # Save hemi vector
    if mask.type == 'HEMI':
        src = get_mask_source(mask)
        save_hemi_props(mask, src)

    mp.halt_reconnect = True

    # Standard bump map is easier to convert
    fine_bump_channels = [ch for ch in mp.channels if ch.enable_smooth_bump]
    for ch in fine_bump_channels:
        ch.enable_smooth_bump = False

    # Disable transition will also helps
    transition_channels = [ch for ch in layer.channels if ch.enable_transition_bump]
    for ch in transition_channels:
        ch.enable_transition_bump = False

    # Current source
    tree = get_mask_tree(mask)
    source = get_mask_source(mask)

    # Save source to cache if it's not image, vertex color, or background
    _save_current_source_to_cache(mask, tree, source, remove_data)

    # Create new source from cache or fresh
    _create_new_source_from_cache_or_new(mask, tree, new_type, item_name, modifier_type)

    # Change mask type
    ori_type = mask.type
    mask.type = new_type

    # Change mask modifier type
    if mask.type == 'MODIFIER':
        mask.modifier_type = modifier_type

    # Set up mapping
    mapping = tree.nodes.get(mask.mapping)
    if is_mapping_possible(new_type):
        if not mapping:
            mapping = new_node(tree, mask, 'mapping', 'ShaderNodeMapping', 'Mask Mapping')
    else:
        remove_node(tree, mask, 'mapping')

    # Update mask name
    image = _update_mask_name_after_replace(mask, layer, mp, ori_type)

    # Set default UV name when necessary
    if is_mapping_possible(mask.type) and mask.uv_name == '':
        obj = get_active_object()
        if obj and obj.type == 'MESH' and len(obj.data.uv_layers) > 0:
            mp.halt_update = True
            mask.uv_name = get_default_uv_name(obj, mp)
            mp.halt_update = False

    # Always remove baked mask when changing type
    if mask.use_baked:
        mask.use_baked = False
        remove_node(tree, mask, 'baked_source')

    # Update group ios
    check_all_layer_channel_io_and_nodes(layer, tree)

    # Back to use fine bump if conversion happen
    for ch in fine_bump_channels:
        ch.enable_smooth_bump = True

    # Bring back transition
    for ch in transition_channels:
        ch.enable_transition_bump = True

    mp.halt_reconnect = False

    # Check uv maps
    check_uv_nodes(mp)

    for lay in mp.layers:
        check_all_layer_channel_io_and_nodes(lay)
        reconnect_layer_nodes(lay)
        rearrange_layer_nodes(lay)

    reconnect_mp_nodes(mask.id_data)
    rearrange_mp_nodes(mask.id_data)

    # Update UI
    bpy.context.window_manager.mpui.need_update = True
    mask.expand_source = (
        mask.type not in {'IMAGE'} or
        (image is not None and image.m_bake_info.is_baked and not image.m_bake_info.is_baked_channel)
    )
