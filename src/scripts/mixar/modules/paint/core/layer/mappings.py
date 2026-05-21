# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ..element.get_elements import get_udim_segment_tiles_height
from ...utils.blender_commons import get_active_object, get_bpy_context
from ..node.get_nodes import get_layer_source, get_mask_source
from ..subtree.get_subtree import get_mask_tree, get_tree

def is_mapping_possible(entity_type, layer=None):
    """Check if mapping is possible for a given entity type.

    Determines whether the specified entity type supports texture mapping.
    Some entity types like vertex colors, backgrounds, and procedural types
    do not support mapping transformations.

    Parameters:
        entity_type (str): The type of entity to check (e.g., 'IMAGE', 'VCOL', 'COLOR').
        layer: Optional layer object to check projection type for COLOR layers.

    Returns:
        bool: True if the entity type supports mapping, False otherwise.
    """
    # Allow mapping for COLOR (Fill) layers when using Decal coordinate type
    # (user explicitly selected Decal, so allow it even for solid color fills)
    if entity_type == 'COLOR' and layer and hasattr(layer, 'texcoord_type'):
        if layer.texcoord_type == 'Decal':
            return True

    # Allow mapping for COLOR (Fill) layers with 3D projections
    if entity_type == 'COLOR' and layer and hasattr(layer, 'projection_type'):
        if layer.projection_type in {'TRIPLANAR', 'PLANAR', 'SPHERICAL', 'CYLINDRICAL', 'DECAL'}:
            logger.debug("[Paint] is_mapping_possible: Returning True (projection_type match)")
            return True

    # Allow mapping for COLOR (Fill) layers with IMAGE source type (uploaded image)
    if entity_type == 'COLOR' and layer and hasattr(layer, 'source_type'):
        if layer.source_type == 'IMAGE':
            logger.debug("[Paint] is_mapping_possible: Returning True (source_type == IMAGE)")
            return True

    # Allow mapping for COLOR (Fill) layers with IMAGE source type (uploaded image)
    if entity_type == 'COLOR' and layer and hasattr(layer, 'source_type'):
        if layer.source_type == 'IMAGE':
            return True

    return entity_type not in {'VCOL', 'BACKGROUND', 'COLOR', 'GROUP', 'HEMI', 'OBJECT_INDEX', 'COLOR_ID', 'BACKFACE', 'EDGE_DETECT', 'MODIFIER', 'AO'} 

def get_layer_mapping(layer, get_baked=False):
    """Retrieve the mapping node for a layer.

    Gets the mapping node from the layer's node tree. Can retrieve either the
    regular mapping node or the baked mapping node.

    Parameters:
        layer: The layer object to get the mapping from.
        get_baked (bool): If True, returns the baked mapping node instead of
                         the regular mapping node. Default: False

    Returns:
        Node or None: The mapping node if it exists, None otherwise.
    """
    tree = get_tree(layer)
    return tree.nodes.get(layer.mapping) if not get_baked else tree.nodes.get(layer.baked_mapping)

def get_mask_mapping(mask, get_baked=False):
    """Retrieve the mapping node for a mask.

    Gets the mapping node from the mask's node tree. Can retrieve either the
    regular mapping node or the baked mapping node.

    Parameters:
        mask: The mask object to get the mapping from.
        get_baked (bool): If True, returns the baked mapping node instead of
                         the regular mapping node. Default: False

    Returns:
        Node or None: The mapping node if it exists, None otherwise.
    """
    tree = get_mask_tree(mask, True)
    return tree.nodes.get(mask.mapping) if not get_baked else tree.nodes.get(mask.baked_mapping)

def get_entity_mapping(entity, get_baked=False):
    """Retrieve the mapping node for any entity (layer or mask).

    Determines whether the entity is a layer or mask by examining its path,
    then retrieves the appropriate mapping node.

    Parameters:
        entity: The entity (layer or mask) to get the mapping from.
        get_baked (bool): If True, returns the baked mapping node instead of
                         the regular mapping node. Default: False

    Returns:
        Node or None: The mapping node if the entity is a layer or mask,
                     None otherwise.
    """
    m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())

    if m1: return get_layer_mapping(entity, get_baked)
    elif m2: return get_mask_mapping(entity, get_baked)

    return None

def get_udim_segment_mapping_offset(segment):
    """Calculate the Y-offset for a UDIM segment in the mapping.

    Computes the vertical offset needed for a specific UDIM segment by
    summing the heights of all segments that come before it in the atlas.

    Parameters:
        segment: The UDIM segment to calculate the offset for.

    Returns:
        int or None: The Y-offset for the segment, or None if the segment
                    is not found in the image's segments.
    """
    image = segment.id_data

    offset_y = 0
    for i, seg in enumerate(image.yua.segments):
        if seg == segment:
            return offset_y
        tiles_height = get_udim_segment_tiles_height(seg)
        offset_y += tiles_height + 1

def clear_mapping(entity, use_baked=False):
    """Reset mapping transformation to default values.

    Clears all transformations on the entity's mapping node by setting
    translation and rotation to (0, 0, 0) and scale to (1, 1, 1).

    Parameters:
        entity: The entity (layer or mask) whose mapping should be cleared.
        use_baked (bool): If True, clears the baked mapping instead of
                         the regular mapping. Default: False

    Returns:
        None
    """
    m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())

    if m1: mapping = get_layer_mapping(entity, use_baked)
    else: mapping = get_mask_mapping(entity, use_baked)

    if mapping:
        mapping.inputs[1].default_value = (0.0, 0.0, 0.0)
        mapping.inputs[2].default_value = (0.0, 0.0, 0.0)
        mapping.inputs[3].default_value = (1.0, 1.0, 1.0)

def update_mapping(entity, use_baked=False):
    """Update the mapping node values based on entity properties.

    Updates the mapping node's transformation values (translation, rotation, scale)
    based on the entity's properties. Handles special cases for image atlases (both
    UDIM and regular image atlases) by calculating appropriate offsets and scales.
    Also triggers UV refresh when in texture paint mode if necessary.

    Parameters:
        entity: The entity (layer or mask) whose mapping should be updated.
        use_baked (bool): If True, updates the baked mapping instead of
                         the regular mapping. Default: False

    Returns:
        None
    """
    mp = entity.id_data.mp

    m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())

    # Get source
    layer = None
    mask = None
    if m1: 
        source = get_layer_source(entity, get_baked=use_baked)
        mapping = get_layer_mapping(entity, get_baked=use_baked)
        layer = entity
    elif m2: 
        source = get_mask_source(entity, get_baked=use_baked)
        mapping = get_mask_mapping(entity, get_baked=use_baked)
        layer = mp.layers[int(m2.group(1))]
        mask = entity
    else: return

    if not mapping: return

    segment_name = entity.segment_name if not use_baked else entity.baked_segment_name

    if use_baked:
        offset_x = offset_y = offset_z = 0.0
        scale_x = scale_y = scale_z = 1.0
    else:
        offset_x = entity.translation[0]
        offset_y = entity.translation[1]
        offset_z = entity.translation[2]

        scale_x = entity.scale[0]
        scale_y = entity.scale[1]
        scale_z = entity.scale[2]

    if (entity.type == 'IMAGE' or use_baked) and segment_name != '':

        # Atlas will only use point vector type for now
        mapping.vector_type = 'POINT'

        image = source.image
        if image.source == 'TILED':
            segment = image.yua.segments.get(segment_name)
            offset_y = get_udim_segment_mapping_offset(segment) 
        else:
            segment = image.yia.segments.get(segment_name)

            scale_x = segment.width / image.size[0] * scale_x
            scale_y = segment.height / image.size[1] * scale_y

            offset_x = scale_x * segment.tile_x + offset_x * scale_x
            offset_y = scale_y * segment.tile_y + offset_y * scale_y

    mapping.inputs[1].default_value = (offset_x, offset_y, offset_z)
    mapping.inputs[2].default_value = entity.rotation
    mapping.inputs[3].default_value = (scale_x, scale_y, scale_z)

    if entity.type == 'IMAGE' and entity.texcoord_type == 'UV':
        context = get_bpy_context()
        if hasattr(context, 'object') and get_active_object() and get_active_object().mode == 'TEXTURE_PAINT':

            # Get active mask of layer
            active_mask = None
            for m in layer.masks:
                if m.active_edit:
                    active_mask = m

            # Only need to refersh if entity is the active one
            if not active_mask or (mask and active_mask == mask):
                mp.need_temp_uv_refresh = True
