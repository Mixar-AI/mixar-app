# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Temporary UV layer management functions.
"""

import re

from ......config.logging_config import get_logger
from ....utils.blender_commons import (
    set_active_mode,
    set_active_object,
)
from ....utils.common import get_first_mirror_modifier
from ....utils.constants import TEMP_UV
from ...layer.mappings import get_layer_mapping, get_mask_mapping
from ...layer.transformations import is_transformed
from ...node.get_nodes import get_layer_source, get_mask_source
from ...subtree.get_subtree import get_mask_tree, get_tree
from ...layer.layer_utils import get_uv_layers
from .uv_mirror import set_uv_mirror_offsets
from .uv_transform import build_transformation_matrix, apply_uv_transformation

logger = get_logger(__name__)


def remove_temp_uv(obj, entity):
    """
    Remove temporary UV layers from the object and restore original mirror modifier offsets.

    This function removes all UV layers with the TEMP_UV name prefix from the object.
    If an entity is provided and has an image atlas, the function also restores the
    original mirror modifier offset values that were stored in the object's mp properties.

    Parameters
    ----------
    obj : bpy.types.Object
        The Blender object from which to remove temporary UV layers.
    entity : object or None
        The entity object (layer or mask). If None, only temp UVs are removed without
        restoring mirror offsets. If provided and valid, mirror modifier offsets are restored.

    Returns
    -------
    None
    """
    uv_layers = get_uv_layers(obj)

    if uv_layers:
        for uv in uv_layers:
            if uv.name == TEMP_UV or uv.name.startswith(TEMP_UV):
                try:
                    uv_layers.remove(uv)
                except Exception as e:
                    logger.error("Error removing temp uv: %s", e)

    if not entity:
        if uv_layers and len(uv_layers) > 0:
            try:
                uv_layers.active = uv_layers[0]
            except Exception as e:
                logger.error("Error setting active uv: %s", e)
        return

    m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())

    if not m1 and not m2:
        return

    # Remove uv mirror offsets for entity with image atlas
    mirror = get_first_mirror_modifier(obj)
    if mirror and entity.type == 'IMAGE' and (
            entity.segment_name != '' or (
                entity.segment_name == '' and obj.mode == 'TEXTURE_PAINT')):
        if mirror.use_mirror_u:
            try:
                mirror.mirror_offset_u = obj.mp.ori_mirror_offset_u
            except Exception as e:
                logger.error("Error setting modifier mirror offset: %s", e)

        if mirror.use_mirror_v:
            try:
                mirror.mirror_offset_v = obj.mp.ori_mirror_offset_v
            except Exception as e:
                logger.error("Error setting modifier mirror offset: %s", e)

        try:
            mirror.offset_u = obj.mp.ori_offset_u
        except Exception as e:
            logger.error("Error setting modifier mirror offset: %s", e)
        try:
            mirror.offset_v = obj.mp.ori_offset_v
        except Exception as e:
            logger.error("Error setting modifier mirror offset: %s", e)


def _get_entity_info(entity):
    """
    Extract entity information and determine entity type.

    Parameters
    ----------
    entity : object
        The entity object (layer, mask, or channel).

    Returns
    -------
    tuple or None
        A tuple of (match, layer, layer_tree) or None if invalid entity.
    """
    m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())
    m3 = re.match(r'^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$', entity.path_from_id())

    if m1 or m2 or m3:
        # Get exact match
        if m1:
            m = m1
        elif m2:
            m = m2
        elif m3:
            m = m3

        # Get layer tree
        mp = entity.id_data.mp
        layer = mp.layers[int(m.group(1))]
        layer_tree = get_tree(layer)
        return m, layer, layer_tree

    return None


def _get_entity_uv(entity, layer, obj):
    """
    Get the appropriate UV layer for the entity.

    Parameters
    ----------
    entity : object
        The entity object.
    layer : object
        The layer object.
    obj : bpy.types.Object
        The Blender object.

    Returns
    -------
    object or None
        The UV layer or None if not found.
    """
    uv_layers = get_uv_layers(obj)
    layer_uv_name = layer.baked_uv_name if layer.use_baked and layer.baked_uv_name != '' else layer.uv_name
    layer_uv = uv_layers.get(layer_uv_name)

    m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
    m3 = re.match(r'^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$', entity.path_from_id())

    if m1 or m3:
        return layer_uv

    uv_name = entity.baked_uv_name if entity.use_baked and entity.baked_uv_name != '' else entity.uv_name
    entity_uv = uv_layers.get(uv_name)

    if not entity_uv:
        entity_uv = layer_uv

    return entity_uv


def _get_source_and_mapping(entity, layer, layer_tree):
    """
    Get the source node and mapping for the entity.

    Parameters
    ----------
    entity : object
        The entity object.
    layer : object
        The layer object.
    layer_tree : object
        The layer's node tree.

    Returns
    -------
    tuple
        A tuple of (source, mapping, entity) where entity may be updated for channels.
    """
    m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())
    m3 = re.match(r'^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$', entity.path_from_id())

    if m1:
        if entity.use_baked:
            tree = get_tree(entity)
            source = tree.nodes.get(entity.baked_source)
        else:
            source = get_layer_source(entity)
        mapping = get_layer_mapping(entity, get_baked=entity.use_baked)
    elif m2:
        if entity.use_baked:
            mask_tree = get_mask_tree(entity)
            source = mask_tree.nodes.get(entity.baked_source)
        else:
            source = get_mask_source(entity)
        mapping = get_mask_mapping(entity, get_baked=entity.use_baked)
    elif m3:
        if entity.active_edit_1:
            source = layer_tree.nodes.get(entity.source_1)
        else:
            source = layer_tree.nodes.get(entity.source)
        mapping = get_layer_mapping(layer)
        entity = layer
    else:
        return None, None, entity

    return source, mapping, entity


def refresh_temp_uv(obj, entity):
    """
    Refresh the temporary UV layer by creating a transformed copy for texture painting.

    This function creates a temporary UV layer with transformations applied based on the
    entity's mapping settings (translation, rotation, scale). The temporary UV is used
    during texture painting or edit mode to allow painting on transformed textures.
    The function handles layers, masks, and channels, and only creates temp UVs when
    necessary (image-based entities with transformations in paint/edit mode).

    Parameters
    ----------
    obj : bpy.types.Object
        The Blender object for which to refresh the temporary UV layer.
    entity : object or None
        The entity object (layer, mask, or channel) containing transformation and
        mapping information. If None, temporary UVs are removed.

    Returns
    -------
    bool
        True if a temporary UV layer was successfully created, False otherwise.
        Returns False if: object is not a mesh, entity is None, entity doesn't use
        an image, object is not in texture paint or edit mode, or mapping is not
        point/texture type.
    """
    if obj.type != 'MESH':
        return False

    if not entity:
        remove_temp_uv(obj, entity)
        return False

    # Get entity info
    entity_info = _get_entity_info(entity)
    if not entity_info:
        return False

    m, layer, layer_tree = entity_info

    uv_layers = get_uv_layers(obj)
    entity_uv = _get_entity_uv(entity, layer, obj)

    if not entity_uv:
        return False

    # Set active uv
    if uv_layers.active != entity_uv:
        try:
            uv_layers.active = entity_uv
        except Exception as e:
            logger.error("Error setting active uv: %s", e)

    # Delete previous temp uv
    remove_temp_uv(obj, entity)

    # Determine entity path type
    m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())
    m3 = re.match(r'^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$', entity.path_from_id())

    # No need to use temp uv if override is not using image
    if m3 and ((entity.active_edit and entity.override_type != 'IMAGE') or
               (entity.active_edit_1 and entity.override_1_type != 'IMAGE')):
        return False

    # No need to use temp uv if layer/mask is not using image
    if (m1 or m2) and (entity.type != 'IMAGE' and not entity.use_baked):
        return False

    # Only set actual uv if not in texture paint or edit mode
    if obj.mode not in {'TEXTURE_PAINT', 'EDIT'}:
        return False

    # Get source and mapping
    source, mapping, entity = _get_source_and_mapping(entity, layer, layer_tree)

    if source is None:
        return False

    # Only point mapping are supported for now
    if mapping and mapping.vector_type not in {'POINT', 'TEXTURE'}:
        return False

    if not hasattr(source, 'image'):
        return False

    img = source.image
    if not img or not mapping or not is_transformed(mapping, entity):
        return False

    set_active_object(obj)

    # Cannot do this in edit mode
    ori_mode = obj.mode
    if ori_mode == 'EDIT':
        set_active_mode('OBJECT')

    # New uv layers
    temp_uv_layer = uv_layers.new(name=TEMP_UV)
    try:
        uv_layers.active = temp_uv_layer
    except Exception as e:
        logger.error("Error setting temporary UV: %s", e)

    # Build transformation matrices
    matrices = build_transformation_matrix(mapping, entity)
    m_mat, m1_mat, m2_mat, m3_mat, m4_mat, translation, rotation, scale = matrices

    if m_mat is None:
        if ori_mode == 'EDIT':
            set_active_mode('EDIT')
        return False

    # Remember the transformation to object props
    obj.mp.texpaint_translation = translation
    obj.mp.texpaint_rotation = rotation
    obj.mp.texpaint_scale = scale

    # Apply UV transformation
    apply_uv_transformation(obj, temp_uv_layer, mapping, m_mat, m1_mat, m2_mat, m3_mat, m4_mat)

    # Set UV mirror offset
    if ori_mode != 'EDIT':
        try:
            set_uv_mirror_offsets(obj, m_mat)
        except Exception as e:
            logger.error("Error setting modifier mirror offset: %s", e)

    # Back to edit mode if originally from there
    if ori_mode == 'EDIT':
        set_active_mode('EDIT')

    return True
