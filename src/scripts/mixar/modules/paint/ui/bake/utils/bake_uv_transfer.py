# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UV transfer operations for baking"""

from mixar.config.logging_config import get_logger

import re

import bpy

logger = get_logger(__name__)

from ....core.element.update_image import replace_image
from ....core.element.update_uv import refresh_temp_uv, set_uv_neighbor_resolution
from ....core.io.utils.io_utils import create_link
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.layer.check_channels import check_all_channel_ios
from ....core.layer.check_layers import any_layers_using_disp, get_first_vdm_layer
from ....core.layer.get_entities import get_mp_entities_images_and_segments
from ....core.layer.layer_utils import get_root_height_channel
from ....core.layer.mappings import (
    get_layer_mapping,
    get_mask_mapping,
    get_udim_segment_mapping_offset,
    update_mapping,
)
from ....core.node.get_nodes import get_layer_source, get_mask_source
from ....core.subtree.get_subtree import get_mask_tree, get_tree
from ....utils.blender_commons import (
    get_active_material,
    get_scene_objects,
    get_unique_name,
    remove_mesh_obj,
    set_active_object,
)
from .bake_common import (
    TEMP_EMISSION,
    bake_entity_as_image,
    get_duplicated_mesh_objects,
    get_merged_mesh_objects,
    is_join_objects_problematic,
)


def transfer_uv(objs, mat, entity, uv_map, is_entity_baked=False):
    """Transfer UV data from one UV map to another by baking.

    Parameters:
        objs (list): List of objects to process
        mat (Material): Material containing the entity
        entity: Layer or mask entity to transfer
        uv_map (str): Target UV map name
        is_entity_baked (bool, optional): Whether entity uses baked source. Default False

    Returns:
        None
    """
    mp = entity.id_data.mp
    scene = bpy.context.scene

    # Check entity
    m1 = re.match(r"^mp\.layers\[(\d+)\]$", entity.path_from_id())
    m2 = re.match(r"^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$", entity.path_from_id())

    if m1:
        if is_entity_baked:
            tree = get_tree(entity)
            source = tree.nodes.get(entity.baked_source)
        else:
            source = get_layer_source(entity)
        mapping = get_layer_mapping(entity)
        index = int(m1.group(1))
    elif m2:
        if is_entity_baked:
            tree = get_mask_tree(entity)
            source = tree.nodes.get(entity.baked_source)
        else:
            source = get_mask_source(entity)
        mapping = get_mask_mapping(entity)
        index = int(m2.group(2))
    else:
        return

    image = source.image
    if not image:
        return

    # Merge objects if necessary
    temp_objs = []
    if len(objs) > 1 and not is_join_objects_problematic(mp):
        objs = temp_objs = [get_merged_mesh_objects(scene, objs)]

    # Set active uv
    for obj in objs:
        if obj.type != "MESH":
            continue
        if uv_map in obj.data.uv_layers:
            obj.data.uv_layers.active = obj.data.uv_layers[uv_map]

    # Some preparations
    ori_material_output = mat.node_tree.nodes.get("Material Output")
    ori_active_obj = bpy.context.active_object

    # Set temp emission
    bpy.data.node_groups[TEMP_EMISSION].nodes["Image Texture"].image = image
    bpy.data.node_groups[TEMP_EMISSION].nodes["Mapping"].inputs["Location"].default_value = (
        mapping.translation
    )
    bpy.data.node_groups[TEMP_EMISSION].nodes["Mapping"].inputs["Rotation"].default_value = (
        mapping.rotation
    )
    bpy.data.node_groups[TEMP_EMISSION].nodes["Mapping"].inputs["Scale"].default_value = (
        mapping.scale
    )

    # Get unique name
    ori_mat_name = mat.name
    temp_mat_name = get_unique_name(ori_mat_name + " TEMP MAT", bpy.data.materials)

    # Create temp mat
    temp_mat = mat.copy()
    temp_mat.name = temp_mat_name

    # Remove all non-bakeable objects with same material
    for obj in get_scene_objects():
        if obj.type != "MESH":
            continue
        for i, slot in enumerate(obj.material_slots):
            if slot.material and slot.material.name == ori_mat_name:
                obj.material_slots[i].material = temp_mat

    # Connect temp emission
    temp_mat_output = temp_mat.node_tree.nodes.get("Material Output")
    temp_emission = temp_mat.node_tree.nodes.new("ShaderNodeGroup")
    temp_emission.node_tree = bpy.data.node_groups[TEMP_EMISSION]
    temp_emission.name = temp_emission.label = "TEMP Emission"

    create_link(
        temp_mat.node_tree,
        temp_emission.outputs[0],
        temp_mat_output.inputs["Surface"],
    )

    # Temp image and uv will be deleted later
    temp_image_name = get_unique_name(image.name + " TEMP IMAGE UV TRANSFER", bpy.data.images)

    # Bake
    bake_entity_as_image(objs, temp_mat, temp_image_name, uv_map, entity, size=(image.size[0], image.size[1]))

    # Get baked image
    temp_image = bpy.data.images.get(temp_image_name)

    # Replace image
    replace_image(temp_image, image)

    # Remove temp image
    bpy.data.images.remove(temp_image)

    # Remove temp material and recover material
    for obj in get_scene_objects():
        if obj.type != "MESH":
            continue
        for i, slot in enumerate(obj.material_slots):
            if slot.material and slot.material.name == temp_mat_name:
                slot.material = mat

    # Remove temp mat
    bpy.data.materials.remove(temp_mat)

    # Change uv name
    if is_entity_baked:
        entity.baked_uv_name = uv_map
    else:
        entity.uv_name = uv_map

    # Update mapping
    if image.yia.is_image_atlas or image.yua.is_udim_atlas:
        segment_name = entity.segment_name if not entity.use_baked else entity.baked_segment_name
        segment = None
        if image.yia.is_image_atlas:
            segment = image.yia.segments.get(segment_name)
        elif image.yua.is_udim_atlas:
            segment = image.yua.segments.get(segment_name)

        if segment:
            offset = get_udim_segment_mapping_offset(segment)
            mapping.translation = (offset[0], offset[1], 0.0)
    else:
        mapping.translation = (0.0, 0.0, 0.0)

    mapping.rotation = (0.0, 0.0, 0.0)
    mapping.scale = (1.0, 1.0, 1.0)

    # Also change other entities which using the same image
    set_entities_which_using_the_same_image_or_segment(entity, uv_map)

    # Recover original active object
    set_active_object(ori_active_obj)

    # Remove duplicated mesh objects
    if temp_objs:
        for temp_obj in temp_objs:
            remove_mesh_obj(scene, temp_obj)


def set_entities_which_using_the_same_image_or_segment(entity, target_uv_name):
    """Set UV name for all entities using the same image or segment as given entity.

    Parameters:
        entity: Layer or mask entity to check
        target_uv_name (str): UV map name to set for matching entities

    Returns:
        None
    """
    mp = entity.id_data.mp

    if entity.type == "IMAGE":
        m = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", entity.path_from_id())

        if m:
            source = get_mask_source(entity)
        else:
            source = get_layer_source(entity)

        image = source.image
        segment_mix_name = (
            image.name + entity.segment_name
            if image and (image.yia.is_image_atlas or image.yua.is_udim_atlas)
            else ""
        )

        for layer in mp.layers:

            for mask in layer.masks:
                if mask == entity or mask.type != "IMAGE":
                    continue
                src = get_mask_source(mask)
                img = src.image

                if img.yia.is_image_atlas or img.yua.is_udim_atlas:
                    if img.name + mask.segment_name == segment_mix_name:
                        mask.uv_name = target_uv_name
                else:
                    if img == image:
                        mask.uv_name = target_uv_name

            if layer == entity or layer.type != "IMAGE":
                continue
            src = get_layer_source(layer)
            img = src.image

            if img.yia.is_image_atlas or img.yua.is_udim_atlas:
                if img.name + layer.segment_name == segment_mix_name:
                    layer.uv_name = target_uv_name
            else:
                if img == image:
                    layer.uv_name = target_uv_name


def get_entities_to_transfer(mp, from_uv_map, to_uv_map):
    """Get list of entities that need UV transfer from one map to another.

    Parameters:
        mp: MPaint node tree data
        from_uv_map (str): Source UV map name
        to_uv_map (str): Target UV map name

    Returns:
        list: List of layer/mask entities that need transferring
    """
    # Check the same images used by multiple layers or masks
    used_images = []
    used_segments = []
    entities = []
    for layer in mp.layers:
        if layer.baked_source != "" and layer.baked_uv_name == from_uv_map:
            if layer not in entities:
                entities.append(layer)

        if layer.type == "IMAGE" and layer.uv_name == from_uv_map:
            source = get_layer_source(layer)
            if source and source.image:
                image = source.image

                if image.yia.is_image_atlas or image.yua.is_udim_atlas:
                    if image.name + layer.segment_name not in used_segments:
                        used_segments.append(image.name + layer.segment_name)
                        if layer not in entities:
                            entities.append(layer)
                else:
                    if image not in used_images:
                        used_images.append(image)
                        if layer not in entities:
                            entities.append(layer)

                if layer not in entities:
                    layer.uv_name = to_uv_map

        for mask in layer.masks:
            if mask.baked_source != "" and mask.baked_uv_name == from_uv_map:
                if mask not in entities:
                    entities.append(mask)

            if mask.type == "IMAGE" and mask.uv_name == from_uv_map:

                source = get_mask_source(mask)
                if source and source.image:
                    image = source.image

                    if image.yia.is_image_atlas or image.yua.is_udim_atlas:
                        if image.name + mask.segment_name not in used_segments:
                            used_segments.append(image.name + mask.segment_name)
                            if mask not in entities:
                                entities.append(mask)
                    else:
                        if image not in used_images:
                            used_images.append(image)
                            if mask not in entities:
                                entities.append(mask)

                    if mask not in entities:
                        mask.uv_name = to_uv_map

    return entities
