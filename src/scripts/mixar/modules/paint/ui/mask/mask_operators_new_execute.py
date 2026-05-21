# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Execute helper functions for MNewLayerMask operator.

This module contains helper functions for executing the MNewLayerMask
operator, handling image creation, vertex color setup, and mask finalization.
"""

import bpy

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.check_elements import check_colorid_vcol
from ...core.element.create_vcol import new_vertex_color
from ...core.element.get_elements import get_vertex_color_names
from ...core.element.update_vcol import set_active_vertex_color
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...core.node.node_utils import get_vertex_colors
from ...utils.blender_commons import get_noncolor_name, get_scene_objects
from ..image_atlas.image_atlas_utils import (
    check_need_of_erasing_segments,
    clear_unused_segments,
    get_set_image_atlas_segment,
)
from ..udim.udim_utils import (
    fill_tile,
    get_set_udim_atlas_segment,
    get_tile_numbers,
    initial_pack_udim,
)
from .mask_creation import add_new_mask
from .mask_removal import remove_mask


def get_to_be_cleared_image_atlas(mask_type, use_image_atlas, mp, color_option, width, height, hdr):
    """Check if an image atlas needs to be cleared for reuse.

    Args:
        mask_type: The type of mask being created.
        use_image_atlas: Whether to use image atlas.
        mp: MPaint node tree property group containing layer and atlas information.
        color_option: Color option (WHITE or BLACK).
        width: Image width.
        height: Image height.
        hdr: Whether to use HDR (32-bit float).

    Returns:
        Image atlas segment object if clearing is needed, None otherwise.
    """
    if mask_type == "IMAGE" and use_image_atlas:
        return check_need_of_erasing_segments(mp, color_option, width, height, hdr)
    return None


def check_duplicate_name(mask_type, name, layer, obj):
    """Check if a mask/image/vcol with the same name already exists.

    Args:
        mask_type: The type of mask being created.
        name: The name to check.
        layer: The layer to check masks in.
        obj: The active Blender object.

    Returns:
        tuple: (has_duplicate: bool, error_type: str or None)
    """
    if mask_type == "IMAGE":
        same_name = [i for i in bpy.data.images if i.name == name]
        if same_name:
            return True, "IMAGE"
    elif mask_type == "VCOL":
        same_name = [i for i in get_vertex_color_names(obj) if i == name]
        if same_name:
            return True, "VCOL"
    else:
        same_name = [m for m in layer.masks if m.name == name]
        if same_name:
            return True, "MASK"
    return False, None


def create_mask_image(name, width, height, color_option, hdr, use_udim, use_image_atlas,
                      mat, uv_name, mp):
    """Create an image for an IMAGE type mask.

    Args:
        name: Image name.
        width: Image width.
        height: Image height.
        color_option: Color option (WHITE or BLACK).
        hdr: Whether to use HDR (32-bit float).
        use_udim: Whether to use UDIM tiles.
        use_image_atlas: Whether to use image atlas.
        mat: The active material.
        uv_name: UV map name.
        mp: MPaint node tree property group.

    Returns:
        tuple: (image, segment) where segment is None if not using atlas.
    """
    alpha = False
    segment = None

    if color_option == "WHITE":
        color = (1, 1, 1, 1)
    elif color_option == "BLACK":
        color = (0, 0, 0, 1)

    if use_udim:
        objs = get_all_objects_with_same_materials(mat)
        tilenums = get_tile_numbers(objs, uv_name)

    if use_image_atlas:
        if use_udim:
            segment = get_set_udim_atlas_segment(
                tilenums,
                width,
                height,
                color,
                get_noncolor_name(),
                hdr,
                mp,
            )
        else:
            segment = get_set_image_atlas_segment(
                width, height, color_option, hdr, mp=mp
            )
        img = segment.id_data
    else:
        if use_udim:
            img = bpy.data.images.new(
                name=name,
                width=width,
                height=height,
                alpha=alpha,
                float_buffer=hdr,
                tiled=True,
            )

            # Fill tiles
            for tilenum in tilenums:
                fill_tile(img, tilenum, color, width, height)
            initial_pack_udim(img, color)
        else:
            img = bpy.data.images.new(
                name=name,
                width=width,
                height=height,
                alpha=alpha,
                float_buffer=hdr,
            )

        img.generated_color = color
        if hasattr(img, "use_alpha"):
            img.use_alpha = False

    if img.colorspace_settings.name != get_noncolor_name() and not img.is_dirty:
        img.colorspace_settings.name = get_noncolor_name()

    return img, segment


def setup_vertex_color_mask(name, color_option, vcol_data_type, vcol_domain,
                            vcol_fill, obj, mat):
    """Set up vertex color for a VCOL type mask.

    Args:
        name: Vertex color name.
        color_option: Color option (WHITE or BLACK).
        vcol_data_type: Vertex color data type.
        vcol_domain: Vertex color domain.
        vcol_fill: Whether to fill selected geometry.
        obj: The active Blender object.
        mat: The active material.

    Returns:
        str: The name of the created vertex color.
    """
    vcol_name = ""

    objs = [obj] if obj.type == "MESH" else []
    if mat.users > 1:
        for o in get_scene_objects():
            if o.type != "MESH":
                continue
            if mat.name in o.data.materials and o not in objs:
                objs.append(o)

    for o in objs:
        if name not in get_vertex_colors(o):
            color = ()
            if color_option == "WHITE":
                color = (1.0, 1.0, 1.0, 1.0)
            elif color_option == "BLACK":
                color = (0.0, 0.0, 0.0, 1.0)

            vcol = new_vertex_color(
                o,
                name,
                vcol_data_type,
                vcol_domain,
                color_fill=color,
            )
            set_active_vertex_color(o, vcol)
            vcol_name = vcol.name

    # Fill selected geometry if in edit mode
    if vcol_fill and bpy.context.mode == "EDIT_MESH" and color_option == "BLACK":
        bpy.ops.mesh.y_vcol_fill(color_option="WHITE")

    return vcol_name


def setup_color_id_mask(color_id, vcol_fill, obj, mat):
    """Set up color ID mask.

    Args:
        color_id: The color ID value (RGB tuple).
        vcol_fill: Whether to fill selected geometry.
        obj: The active Blender object.
        mat: The active material.
    """
    objs = [obj] if obj.type == "MESH" else []
    if mat.users > 1:
        for o in get_scene_objects():
            if o.type != "MESH":
                continue
            if mat.name in o.data.materials and o not in objs:
                objs.append(o)

    check_colorid_vcol(objs, set_as_active=True)

    # Fill selected geometry if in edit mode
    if vcol_fill and bpy.context.mode == "EDIT_MESH":
        bpy.ops.mesh.y_vcol_fill_face_custom(
            color=(
                color_id[0],
                color_id[1],
                color_id[2],
                1.0,
            )
        )


def finalize_mask_creation(mask, mask_type, layer, mpui):
    """Finalize mask creation by reconnecting nodes and updating UI.

    Args:
        mask: The created mask.
        mask_type: The type of mask created.
        layer: The layer containing the mask.
        mpui: The MPaint UI property group.
    """
    # Enable edit mask
    if mask_type in {"IMAGE", "VCOL", "COLOR_ID"}:
        mask.active_edit = True

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(layer.id_data)
    rearrange_mp_nodes(layer.id_data)

    # Update UI
    mpui.layer_ui.expand_masks = True
    if mask_type not in {"IMAGE", "VCOL", "BACKFACE"}:
        mask.expand_content = True
        mask.expand_source = True
    mpui.need_update = True


__all__ = [
    'get_to_be_cleared_image_atlas',
    'check_duplicate_name',
    'create_mask_image',
    'setup_vertex_color_mask',
    'setup_color_id_mask',
    'finalize_mask_creation',
    'add_new_mask',
    'remove_mask',
    'clear_unused_segments',
]
