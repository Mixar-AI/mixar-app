# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer mask setup helper functions."""

import os

import bpy

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.element.check_elements import check_colorid_vcol
from ....core.element.create_vcol import new_vertex_color
from ....core.element.update_vcol import set_active_vertex_color
from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.node.node_utils import get_vertex_colors
from ....utils.blender_commons import (
    get_noncolor_name,
    get_scene_objects,
    load_image,
)
from ...image_atlas.image_atlas_utils import get_set_image_atlas_segment
from ...mask.mask_creation import add_new_mask
from ...mask.mask_operators_helper import get_new_mask_name
from ...udim.udim_operators_helper import fill_tile
from ...udim.udim_utils import (
    get_set_udim_atlas_segment,
    get_tile_numbers,
    initial_pack_udim,
)


def setup_layer_mask(
    layer,
    obj,
    mat,
    mp,
    mask_type="IMAGE",
    mask_image_filepath="",
    mask_relative=True,
    mask_texcoord_type="UV",
    mask_color="BLACK",
    mask_use_hdr=False,
    mask_uv_name="",
    mask_width=1024,
    mask_height=1024,
    use_image_atlas_for_mask=False,
    mask_color_id=(1, 0, 1),
    mask_vcol_fill=True,
    mask_vcol_data_type="BYTE_COLOR",
    mask_vcol_domain="CORNER",
    use_udim_for_mask=False,
    mask_interpolation="Linear",
    mask_edge_detect_radius=0.05,
    mask_use_prev_normal=True,
):
    """Set up a mask for a layer.

    Args:
        layer: The layer to add the mask to.
        obj: The active object.
        mat: The active material.
        mp: The mixar paint data structure.
        mask_type (str, optional): Type of mask (IMAGE, VCOL, etc.). Defaults to "IMAGE".
        mask_image_filepath (str, optional): Path to mask image file. Defaults to "".
        mask_relative (bool, optional): Use relative path for mask image. Defaults to True.
        mask_texcoord_type (str, optional): Texture coordinate type for mask. Defaults to "UV".
        mask_color (str, optional): Initial mask color (BLACK or WHITE). Defaults to "BLACK".
        mask_use_hdr (bool, optional): Use HDR for mask image. Defaults to False.
        mask_uv_name (str, optional): UV map name for mask. Defaults to "".
        mask_width (int, optional): Width of mask image in pixels. Defaults to 1024.
        mask_height (int, optional): Height of mask image in pixels. Defaults to 1024.
        use_image_atlas_for_mask (bool, optional): Use image atlas for mask. Defaults to False.
        mask_color_id (tuple, optional): Color ID for mask. Defaults to (1, 0, 1).
        mask_vcol_fill (bool, optional): Fill vertex color mask. Defaults to True.
        mask_vcol_data_type (str, optional): Vertex color data type. Defaults to "BYTE_COLOR".
        mask_vcol_domain (str, optional): Vertex color domain. Defaults to "CORNER".
        use_udim_for_mask (bool, optional): Use UDIM tiles for mask. Defaults to False.
        mask_interpolation (str, optional): Mask interpolation type. Defaults to "Linear".
        mask_edge_detect_radius (float, optional): Edge detection radius for mask. Defaults to 0.05.
        mask_use_prev_normal (bool, optional): Use previous normal for mask. Defaults to True.

    Returns:
        The created mask object, or None if mask creation was cancelled.
    """
    mask_name = get_new_mask_name(obj, layer, mask_type)
    mask_image = None
    mask_vcol_name = ""
    mask_segment = None

    if mask_type == "IMAGE":
        result = _setup_image_mask(
            mask_name=mask_name,
            mask_image_filepath=mask_image_filepath,
            mask_relative=mask_relative,
            mask_color=mask_color,
            mask_use_hdr=mask_use_hdr,
            mask_uv_name=mask_uv_name,
            mask_width=mask_width,
            mask_height=mask_height,
            use_image_atlas_for_mask=use_image_atlas_for_mask,
            use_udim_for_mask=use_udim_for_mask,
            mat=mat,
            mp=mp,
        )
        if result is None:
            return None
        mask_image, mask_segment = result

    elif mask_type in {"VCOL", "COLOR_ID"}:
        mask_vcol_name = _setup_vcol_mask(
            mask_name=mask_name,
            mask_type=mask_type,
            mask_color=mask_color,
            mask_vcol_fill=mask_vcol_fill,
            mask_vcol_data_type=mask_vcol_data_type,
            mask_vcol_domain=mask_vcol_domain,
            mask_color_id=mask_color_id,
            obj=obj,
            mat=mat,
        )

    mask = add_new_mask(
        layer,
        mask_name,
        mask_type,
        mask_texcoord_type,
        mask_uv_name,
        mask_image,
        mask_vcol_name,
        mask_segment,
        interpolation=mask_interpolation,
        color_id=mask_color_id,
        edge_detect_radius=mask_edge_detect_radius,
        hemi_use_prev_normal=mask_use_prev_normal,
    )
    mask.active_edit = True

    return mask


def _setup_image_mask(
    mask_name,
    mask_image_filepath,
    mask_relative,
    mask_color,
    mask_use_hdr,
    mask_uv_name,
    mask_width,
    mask_height,
    use_image_atlas_for_mask,
    use_udim_for_mask,
    mat,
    mp,
):
    """Set up an image-based mask.

    Args:
        mask_name (str): Name for the mask.
        mask_image_filepath (str): Path to mask image file.
        mask_relative (bool): Use relative path for mask image.
        mask_color (str): Initial mask color (BLACK or WHITE).
        mask_use_hdr (bool): Use HDR for mask image.
        mask_uv_name (str): UV map name for mask.
        mask_width (int): Width of mask image in pixels.
        mask_height (int): Height of mask image in pixels.
        use_image_atlas_for_mask (bool): Use image atlas for mask.
        use_udim_for_mask (bool): Use UDIM tiles for mask.
        mat: The active material.
        mp: The mixar paint data structure.

    Returns:
        tuple: (mask_image, mask_segment) or None if cancelled.
    """
    mask_image = None
    mask_segment = None

    if not mask_image_filepath:
        color = (0, 0, 0, 0)
        if mask_color == "WHITE":
            color = (1, 1, 1, 1)
        elif mask_color == "BLACK":
            color = (0, 0, 0, 1)

        tilenums = None
        if use_udim_for_mask:
            objs = get_all_objects_with_same_materials(mat)
            tilenums = get_tile_numbers(objs, mask_uv_name)

        if use_image_atlas_for_mask:
            mask_image, mask_segment = _create_atlas_mask(
                tilenums=tilenums,
                mask_width=mask_width,
                mask_height=mask_height,
                color=color,
                mask_use_hdr=mask_use_hdr,
                use_udim_for_mask=use_udim_for_mask,
                mask_color=mask_color,
                mp=mp,
            )
        else:
            mask_image = _create_standard_mask(
                mask_name=mask_name,
                tilenums=tilenums,
                mask_width=mask_width,
                mask_height=mask_height,
                color=color,
                mask_use_hdr=mask_use_hdr,
                use_udim_for_mask=use_udim_for_mask,
            )
    else:
        mask_image = _load_mask_from_file(mask_image_filepath, mask_relative)
        if mask_image is None:
            return None

    # Set colorspace if needed
    if (
        mask_image.colorspace_settings.name != get_noncolor_name()
        and not mask_image.is_dirty
    ):
        mask_image.colorspace_settings.name = get_noncolor_name()

    return mask_image, mask_segment


def _create_atlas_mask(
    tilenums,
    mask_width,
    mask_height,
    color,
    mask_use_hdr,
    use_udim_for_mask,
    mask_color,
    mp,
):
    """Create a mask using image atlas.

    Args:
        tilenums: UDIM tile numbers.
        mask_width (int): Width of mask image.
        mask_height (int): Height of mask image.
        color (tuple): RGBA color.
        mask_use_hdr (bool): Use HDR for mask.
        use_udim_for_mask (bool): Use UDIM tiles.
        mask_color (str): Mask color option.
        mp: The mixar paint data structure.

    Returns:
        tuple: (mask_image, mask_segment)
    """
    if use_udim_for_mask:
        mask_segment = get_set_udim_atlas_segment(
            tilenums,
            mask_width,
            mask_height,
            color,
            colorspace=get_noncolor_name(),
            hdr=mask_use_hdr,
            mp=mp,
        )
    else:
        mask_segment = get_set_image_atlas_segment(
            mask_width, mask_height, mask_color, mask_use_hdr, mp=mp
        )
    mask_image = mask_segment.id_data
    return mask_image, mask_segment


def _create_standard_mask(
    mask_name,
    tilenums,
    mask_width,
    mask_height,
    color,
    mask_use_hdr,
    use_udim_for_mask,
):
    """Create a standard (non-atlas) mask image.

    Args:
        mask_name (str): Name for the mask image.
        tilenums: UDIM tile numbers.
        mask_width (int): Width of mask image.
        mask_height (int): Height of mask image.
        color (tuple): RGBA color.
        mask_use_hdr (bool): Use HDR for mask.
        use_udim_for_mask (bool): Use UDIM tiles.

    Returns:
        The created mask image.
    """
    if use_udim_for_mask:
        mask_image = bpy.data.images.new(
            mask_name,
            width=mask_width,
            height=mask_height,
            alpha=False,
            float_buffer=mask_use_hdr,
            tiled=True,
        )

        # Fill tiles
        for tilenum in tilenums:
            fill_tile(mask_image, tilenum, color, mask_width, mask_height)
        initial_pack_udim(mask_image, color)
    else:
        mask_image = bpy.data.images.new(
            mask_name,
            width=mask_width,
            height=mask_height,
            alpha=False,
            float_buffer=mask_use_hdr,
        )

    mask_image.generated_color = color
    if hasattr(mask_image, "use_alpha"):
        mask_image.use_alpha = False

    return mask_image


def _load_mask_from_file(mask_image_filepath, mask_relative):
    """Load a mask image from file.

    Args:
        mask_image_filepath (str): Path to the mask image file.
        mask_relative (bool): Use relative path.

    Returns:
        The loaded mask image, or None if file not found.
    """
    if not os.path.isfile(mask_image_filepath):
        logger.warning("There's no image with address '%s'!", mask_image_filepath)
        return None

    path = os.path.basename(mask_image_filepath)
    directory = os.path.dirname(mask_image_filepath)

    mask_image = load_image(path, directory)

    if mask_relative and bpy.data.filepath != "":
        try:
            mask_image.filepath = bpy.path.relpath(mask_image.filepath)
        except:
            pass

    return mask_image


def _setup_vcol_mask(
    mask_name,
    mask_type,
    mask_color,
    mask_vcol_fill,
    mask_vcol_data_type,
    mask_vcol_domain,
    mask_color_id,
    obj,
    mat,
):
    """Set up a vertex color or color ID mask.

    Args:
        mask_name (str): Name for the mask.
        mask_type (str): Type of mask (VCOL or COLOR_ID).
        mask_color (str): Initial mask color (BLACK or WHITE).
        mask_vcol_fill (bool): Fill vertex color mask.
        mask_vcol_data_type (str): Vertex color data type.
        mask_vcol_domain (str): Vertex color domain.
        mask_color_id (tuple): Color ID for mask.
        obj: The active object.
        mat: The active material.

    Returns:
        str: The vertex color name for VCOL masks, empty string otherwise.
    """
    objs = [obj] if obj.type == "MESH" else []
    if mat.users > 1:
        for o in get_scene_objects():
            if o.type != "MESH":
                continue
            if mat.name in o.data.materials and o not in objs:
                objs.append(o)

    mask_vcol_name = ""

    if mask_type == "VCOL":
        mask_vcol_name = _create_vcol_mask(
            objs=objs,
            mask_name=mask_name,
            mask_color=mask_color,
            mask_vcol_fill=mask_vcol_fill,
            mask_vcol_data_type=mask_vcol_data_type,
            mask_vcol_domain=mask_vcol_domain,
        )
    elif mask_type == "COLOR_ID":
        _create_color_id_mask(
            objs=objs,
            mask_vcol_fill=mask_vcol_fill,
            mask_color_id=mask_color_id,
        )

    return mask_vcol_name


def _create_vcol_mask(
    objs,
    mask_name,
    mask_color,
    mask_vcol_fill,
    mask_vcol_data_type,
    mask_vcol_domain,
):
    """Create a vertex color mask.

    Args:
        objs: List of objects to create vertex colors on.
        mask_name (str): Name for the vertex color.
        mask_color (str): Initial mask color (BLACK or WHITE).
        mask_vcol_fill (bool): Fill vertex color mask.
        mask_vcol_data_type (str): Vertex color data type.
        mask_vcol_domain (str): Vertex color domain.

    Returns:
        str: The vertex color name.
    """
    mask_vcol_name = ""

    for o in objs:
        if mask_name not in get_vertex_colors(o):
            color = ()
            if mask_color == "WHITE":
                color = (1.0, 1.0, 1.0, 1.0)
            elif mask_color == "BLACK":
                color = (0.0, 0.0, 0.0, 1.0)

            mask_vcol = new_vertex_color(
                o,
                mask_name,
                mask_vcol_data_type,
                mask_vcol_domain,
                color_fill=color,
            )
            set_active_vertex_color(o, mask_vcol)
            mask_vcol_name = mask_vcol.name

    # Fill selected geometry if in edit mode
    if mask_vcol_fill and bpy.context.mode == "EDIT_MESH":
        bpy.ops.mesh.y_vcol_fill(color_option="WHITE")

    return mask_vcol_name


def _create_color_id_mask(objs, mask_vcol_fill, mask_color_id):
    """Create a color ID mask.

    Args:
        objs: List of objects.
        mask_vcol_fill (bool): Fill vertex color mask.
        mask_color_id (tuple): Color ID for mask.
    """
    check_colorid_vcol(objs, set_as_active=True)

    # Fill selected geometry if in edit mode
    if mask_vcol_fill and bpy.context.mode == "EDIT_MESH":
        bpy.ops.mesh.y_vcol_fill_face_custom(
            color=(
                mask_color_id[0],
                mask_color_id[1],
                mask_color_id[2],
                1.0,
            )
        )
