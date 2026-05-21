# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Utility functions for baking operations"""

import os

import bpy

from ....core.element.update_image import copy_image_pixels
from ....core.layer.mappings import clear_mapping, get_udim_segment_mapping_offset
from ....core.node.get_nodes import get_active_mat_output_node
from ...image_atlas.image_atlas_utils import (
    check_need_of_erasing_segments,
    clear_unused_segments,
    get_set_image_atlas_segment,
)
from ...udim.udim_utils import copy_tiles, get_set_udim_atlas_segment
from ....utils.blender_commons import (
    get_noncolor_name,
    get_viewport_context,
    remove_datablock,
)

# Constants for temp materials
TEMP_EMIT_WHITE = "__EMIT_WHITE__"
TEMP_MATERIAL = "__TEMP_MATERIAL_"


def create_plane_on_object_mode():
    """Create a plane mesh object in object mode.

    Returns:
        Object: The created plane object.
    """

    # Mesh primitive operators need viewport context
    viewport_ctx = get_viewport_context()

    if viewport_ctx:
        with bpy.context.temp_override(**viewport_ctx):
            bpy.ops.mesh.primitive_plane_add(calc_uvs=True)
    else:
        # Fallback without context override
        bpy.ops.mesh.primitive_plane_add(calc_uvs=True)

    return bpy.context.view_layer.objects.active


def get_valid_filepath(img, use_hdr):
    """Get valid filepath for image based on HDR requirement.

    Args:
        img: Blender image object.
        use_hdr (bool): Whether HDR format is needed.

    Returns:
        str: Valid filepath with appropriate extension.
    """
    if img.filepath != "":
        prefix, ext = os.path.splitext(img.filepath)
        if use_hdr and not img.is_float:
            # if ext == '.png':
            return prefix + ".exr"
        elif not use_hdr and img.is_float:
            # if ext == '.exr':
            return prefix + ".png"

    return img.filepath


def put_image_to_image_atlas(mp, image, tilenums=[]):
    """Put a baked image into the image atlas system.

    Args:
        mp: MPaint node tree property group.
        image: Blender image object to add to atlas.
        tilenums (list, optional): List of UDIM tile numbers. Defaults to [].

    Returns:
        tuple: (ia_image, segment) tuple containing atlas image and segment.
    """

    if image.source == "TILED":
        segment = get_set_udim_atlas_segment(
            tilenums,
            color=(0, 0, 0, 1),
            colorspace=get_noncolor_name(),
            hdr=image.is_float,
            mp=mp,
        )
    else:
        # Clearing unused image atlas segments
        img_atlas = check_need_of_erasing_segments(
            mp, "TRANSPARENT", image.size[0], image.size[1], image.is_float
        )
        if img_atlas:
            clear_unused_segments(img_atlas.yia)

        segment = get_set_image_atlas_segment(
            image.size[0], image.size[1], "TRANSPARENT", image.is_float, mp=mp
        )

    ia_image = segment.id_data

    # Set baked image to segment
    if image.source == "TILED":
        offset = get_udim_segment_mapping_offset(segment) * 10
        copy_dict = {}
        for tilenum in tilenums:
            copy_dict[tilenum] = tilenum + offset
        copy_tiles(image, ia_image, copy_dict)
    else:
        copy_image_pixels(image, ia_image, segment)

    # Remove original baked image
    remove_datablock(bpy.data.images, image)

    return ia_image, segment


def get_temp_default_material():
    """Get or create a temporary default material.

    Returns:
        Material: Temporary default material object.
    """
    mat = bpy.data.materials.get(TEMP_MATERIAL)

    if not mat:
        mat = bpy.data.materials.new(TEMP_MATERIAL)
        mat.use_nodes = True

    return mat


def remove_temp_default_material():
    """Remove temporary default material if it exists."""
    mat = bpy.data.materials.get(TEMP_MATERIAL)
    if mat:
        remove_datablock(bpy.data.materials, mat)


def get_temp_emit_white_mat():
    """Get or create a temporary white emission material.

    Returns:
        Material: Temporary white emission material object.
    """
    mat = bpy.data.materials.get(TEMP_EMIT_WHITE)

    if not mat:
        mat = bpy.data.materials.new(TEMP_EMIT_WHITE)
        mat.use_nodes = True

        # Create nodes
        output = get_active_mat_output_node(mat.node_tree)
        emi = mat.node_tree.nodes.new("ShaderNodeEmission")
        mat.node_tree.links.new(emi.outputs[0], output.inputs[0])

    return mat


def remove_temp_emit_white_mat():
    """Remove temporary white emission material if it exists."""
    mat = bpy.data.materials.get(TEMP_EMIT_WHITE)
    if mat:
        remove_datablock(bpy.data.materials, mat)
