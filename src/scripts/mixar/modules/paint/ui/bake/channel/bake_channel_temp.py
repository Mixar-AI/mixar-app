# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Temporary baking functions for channel baking operations."""

from mixar.config.logging_config import get_logger

import re
import time

import bpy

logger = get_logger(__name__)

# Core imports
from ....core.layer.get_entities import get_mp_entities_images_and_segments
from ....core.node.get_nodes import get_layer_source, get_mask_source, get_active_mat_output_node

# Utility imports
from ....utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_noncolor_name,
    simple_remove_node,
)
from ....utils.classes import dotdict

# Layer and mask helpers
from ...layer.helpers.layer_operation_helpers import replace_layer_type
from ...mask.mask_operators_helper import replace_mask_type

# Bake common imports
from ..utils.bake_common import (
    bake_object_op,
    prepare_bake_settings,
    recover_bake_settings,
    remember_before_bake,
)


def temp_bake(
    context,
    entity,
    width,
    height,
    hdr,
    samples,
    margin,
    uv_map,
    bake_device="CPU",
    margin_type="ADJACENT_FACES",
):
    """Temporarily bake entity to image for processing.

    Parameters:
        context: Blender context
        entity: Layer or mask to bake
        width (int): Bake image width
        height (int): Bake image height
        hdr (bool): Use HDR/float image
        samples (int): Number of samples for baking
        margin (int): Margin size in pixels
        uv_map (str): UV map name
        bake_device (str, optional): Device to use for baking. Default "CPU"
        margin_type (str, optional): Margin type. Default "ADJACENT_FACES"

    Returns:
        Image or None: The baked image if successful
    """
    m1 = re.match(r"mp\.layers\[(\d+)\]$", entity.path_from_id())
    m2 = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]$", entity.path_from_id())

    if not m1 and not m2:
        return None

    mp = entity.id_data.mp
    obj = get_active_object()

    # Prepare bake settings
    book = remember_before_bake(mp)
    prepare_bake_settings(
        book,
        [obj],
        mp,
        samples,
        margin,
        uv_map,
        bake_device=bake_device,
        margin_type=margin_type,
    )

    mat = get_active_material()
    name = entity.name + " Temp"

    # New target image
    image = bpy.data.images.new(
        name=name, width=width, height=height, alpha=True, float_buffer=hdr
    )
    image.colorspace_settings.name = get_noncolor_name()

    if entity.type == "HEMI":
        if m1:
            source = get_layer_source(entity)
        else:
            source = get_mask_source(entity)

        # Create bake nodes
        source_copy = mat.node_tree.nodes.new(source.bl_idname)
        source_copy.node_tree = source.node_tree

        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        emit = mat.node_tree.nodes.new("ShaderNodeEmission")
        geo = mat.node_tree.nodes.new("ShaderNodeNewGeometry")
        output = get_active_mat_output_node(mat.node_tree)
        ori_bsdf = output.inputs[0].links[0].from_socket

        # Connect emit to output material
        mat.node_tree.links.new(emit.outputs[0], output.inputs[0])
        mat.node_tree.links.new(source_copy.outputs[0], output.inputs[0])
        mat.node_tree.links.new(geo.outputs["Normal"], source_copy.inputs["Normal"])

        # Set active texture
        tex.image = image
        mat.node_tree.nodes.active = tex

        # Bake
        bake_object_op()

        # Recover link
        mat.node_tree.links.new(ori_bsdf, output.inputs[0])

        # Remove temp nodes
        mat.node_tree.nodes.remove(tex)
        simple_remove_node(mat.node_tree, emit)
        simple_remove_node(mat.node_tree, source_copy)
        simple_remove_node(mat.node_tree, geo)

        # Set entity original type
        entity.original_type = "HEMI"

    # Set entity flag
    entity.use_temp_bake = True

    # Recover bake settings
    recover_bake_settings(book, mp)

    # Set uv
    entity.uv_name = uv_map

    # Replace layer with temp image
    if m1:
        replace_layer_type(entity, "IMAGE", image.name, remove_data=True)
    else:
        replace_mask_type(entity, "IMAGE", image.name, remove_data=True)

    return image


def disable_temp_bake(entity):
    """Disable temporary bake and restore entity to original type.

    Parameters:
        entity: Layer or mask with temp bake enabled

    Returns:
        None
    """
    if not entity.use_temp_bake:
        return

    m1 = re.match(r"mp\.layers\[(\d+)\]$", entity.path_from_id())
    m2 = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]$", entity.path_from_id())

    # Replace layer type
    if m1:
        replace_layer_type(entity, entity.original_type, remove_data=True)
    else:
        replace_mask_type(entity, entity.original_type, remove_data=True)

    # Set entity attribute
    entity.use_temp_bake = False


def rebake_baked_images(mp, specific_layers=None):
    """Rebake all baked images in MPaint node.

    Parameters:
        mp: MPaint node tree data
        specific_layers (list, optional): List of specific layers to rebake. Default None

    Returns:
        int: Number of images successfully rebaked
    """
    # Import here to avoid circular imports
    from ..utils.bake_common import bake_entity_as_image
    from .bake_to_entity import bake_to_entity

    if specific_layers is None:
        specific_layers = []

    tt = time.time()
    logger.info("Rebaking images is started...")

    entities, images, segment_names, segment_name_props = (
        get_mp_entities_images_and_segments(mp, specific_layers=specific_layers)
    )

    baked_counts = 0

    for i, image in enumerate(images):
        logger.info("Rebaking image '%s'...", image.name)

        if image.yia.is_image_atlas:
            segment = image.yia.segments.get(segment_names[i])
        elif image.yua.is_udim_atlas:
            segment = image.yua.segments.get(segment_names[i])
        else:
            segment = None

        if (
            segment
            and segment.bake_info.is_baked
            and not segment.bake_info.is_baked_channel
        ) or (
            not segment
            and image.m_bake_info.is_baked
            and not image.m_bake_info.is_baked_channel
        ):

            bi = image.m_bake_info if not segment else segment.bake_info

            # Skip outdated bake type
            if bi.bake_type == "SELECTED_VERTICES":
                continue

            entity = entities[i][0]
            entity_path = entity.path_from_id()
            segment_name_prop = segment_name_props[i][0]

            m1 = re.match(r"^mp\.layers\[(\d+)\]$", entity_path)
            m2 = re.match(r"^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$", entity_path)

            bake_properties = dotdict()
            for attr in dir(bi):
                if attr.startswith("__"):
                    continue
                if attr.startswith("bl_"):
                    continue
                if attr in {"rna_type"}:
                    continue
                try:
                    bake_properties[attr] = getattr(bi, attr)
                except Exception:
                    pass

            bake_properties.update(
                {
                    "type": bi.bake_type,
                    "target_type": "LAYER" if m1 or m2 else "MASK",
                    "name": image.name,
                    "width": image.size[0] if not segment else segment.width,
                    "height": image.size[1] if not segment else segment.height,
                    "uv_map": (
                        entity.uv_name if not entity.use_baked else entity.baked_uv_name
                    ),
                }
            )

            # 'baked_segment_name' meant the entity is baked as image
            if segment_name_prop == "baked_segment_name":
                bake_entity_as_image(
                    entity, bprops=bake_properties, set_image_to_entity=True
                )
            else:
                bake_to_entity(
                    bprops=bake_properties, overwrite_img=image, segment=segment
                )

            baked_counts += 1

    logger.info(
        "Rebaking images is done at %s seconds!",
        "{:0.2f}".format(time.time() - tt),
    )

    return baked_counts
