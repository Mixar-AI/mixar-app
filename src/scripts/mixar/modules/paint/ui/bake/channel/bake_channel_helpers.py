# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for channel baking - image creation, color setup, and node configuration."""

from mixar.config.logging_config import get_logger

import bpy
from mathutils import Color

logger = get_logger(__name__)

# Core imports
from ....core.layer.check_layers import is_root_ch_prop_node_unique
from ....core.lib.lib import NORMAL_MAP_PREP_LEGACY
from ....core.node.create_nodes import new_node
from ....core.node.get_nodes import get_layer_source
from ....core.node.node_utils import get_node_tree_lib

# Utility imports
from ....utils.blender_commons import (
    get_noncolor_name,
    get_srgb_name,
    linear_to_srgb,
)

# UDIM imports
from ...udim.udim_operators_helper import fill_tile
from ...udim.udim_utils import (
    get_udim_segment_base_tilenums,
    initial_pack_udim,
)
from ...udim.udim_utils_segment import get_udim_segment_tilenums

# Bake common imports
from ..utils.bake_common import get_valid_filepath


def determine_bake_color(root_ch, node, mp, channel_idx, segment=None, source=None):
    """Determine the background color for baking based on channel type.

    Parameters:
        root_ch: Root channel being baked
        node: MPaint node
        mp: MPaint node tree data
        channel_idx (int): Index of the channel
        segment: Optional segment for atlas images
        source: Optional source node for segment

    Returns:
        tuple: RGBA color tuple (r, g, b, a)
        dict or None: Copy dictionary for UDIM segments
        list or None: Tile numbers for UDIM segments
    """
    copy_dict = None
    tilenums = None

    if segment:
        if source.image.yia.is_image_atlas:
            if source.image.yia.color == "WHITE":
                color = (1.0, 1.0, 1.0, 1.0)
            elif source.image.yia.color == "BLACK":
                color = (0.0, 0.0, 0.0, 1.0)
            else:
                color = (0.0, 0.0, 0.0, 0.0)
        else:
            copy_dict = {}
            segment_tilenums = get_udim_segment_tilenums(segment)
            tilenums = get_udim_segment_base_tilenums(segment)
            color = segment.base_color

    elif root_ch.type == "NORMAL":
        color = (0.5, 0.5, 1.0, 1.0)

    elif root_ch.type == "VALUE":
        val = node.inputs[root_ch.name].default_value
        color = (val, val, val, 1.0)

    elif root_ch.enable_alpha:
        color = (0.0, 0.0, 0.0, 1.0)

    else:
        # Check for solid color base layer
        base_solid_color = None
        for layer in mp.layers:
            if (
                not layer.enable
                or layer.type != "COLOR"
                or len(layer.masks) > 0
                or layer.parent_idx != -1
            ):
                continue
            c = layer.channels[channel_idx]
            if not c.enable or c.override:
                continue
            layer_source = get_layer_source(layer)
            if layer_source:
                base_solid_color = layer_source.outputs[0].default_value
                break

        if base_solid_color is not None:
            col = base_solid_color
        else:
            col = node.inputs[root_ch.name].default_value

        col = Color((col[0], col[1], col[2]))
        col = linear_to_srgb(col)
        color = (col.r, col.g, col.b, 1.0)

    return color, copy_dict, tilenums


def create_bake_image(
    img_name,
    width,
    height,
    root_ch,
    color,
    use_udim,
    use_hdr,
    use_float_for_normal,
    tilenums,
    filepath="",
    segment=None,
    source=None,
    copy_dict=None,
    segment_tilenums=None,
):
    """Create a new image for baking.

    Parameters:
        img_name (str): Name for the new image
        width (int): Image width
        height (int): Image height
        root_ch: Root channel being baked
        color (tuple): Background color (r, g, b, a)
        use_udim (bool): Whether to create UDIM tiled image
        use_hdr (bool): Whether to use HDR/float image
        use_float_for_normal (bool): Use float for normal maps
        tilenums (list): Tile numbers for UDIM
        filepath (str, optional): Filepath for the image
        segment: Optional segment for atlas images
        source: Optional source node for segment
        copy_dict (dict, optional): Copy dictionary for UDIM
        segment_tilenums (list, optional): Segment tile numbers

    Returns:
        Image: Created Blender image datablock
    """
    # Calculate float_buffer setting
    should_be_float = (root_ch.type == "NORMAL" and use_float_for_normal) or use_hdr
    logger.info(
        "CREATE_BAKE_IMAGE: root_ch.type=%s, use_float_for_normal=%s, use_hdr=%s -> float_buffer=%s",
        root_ch.type, use_float_for_normal, use_hdr, should_be_float
    )

    if use_udim:
        # Create new UDIM image
        img = bpy.data.images.new(
            name=img_name,
            width=width,
            height=height,
            alpha=True,
            tiled=True,
            float_buffer=should_be_float,
        )

        # Fill tiles
        if segment and copy_dict is not None and segment_tilenums:
            for i, tilenum in enumerate(tilenums):
                tile = source.image.tiles.get(segment_tilenums[i])
                copy_dict[tilenum] = segment_tilenums[i]
                if tile:
                    fill_tile(img, tilenum, color, tile.size[0], tile.size[1])
        else:
            for tilenum in tilenums:
                fill_tile(img, tilenum, color, width, height)

        initial_pack_udim(img, color)

    else:
        # Create new standard image
        img = bpy.data.images.new(
            name=img_name,
            width=width,
            height=height,
            alpha=True,
            float_buffer=should_be_float,
        )
        img.generated_type = "BLANK"

    logger.info("CREATE_BAKE_IMAGE: Created image '%s', is_float=%s", img.name, img.is_float)

    # Set image base color
    if hasattr(img, "use_alpha"):
        img.use_alpha = True
    img.generated_color = color

    # Set filepath
    if filepath != "" and (
        (use_udim and ".<UDIM>." in filepath)
        or (not use_udim and ".<UDIM>." not in filepath)
    ):
        img.filepath = filepath

    # Set colorspace
    if (
        root_ch.colorspace == "LINEAR"
        or root_ch.type == "NORMAL"
        or root_ch.type == "VALUE"
        or use_hdr
    ):
        img.colorspace_settings.name = get_noncolor_name()
    else:
        img.colorspace_settings.name = get_srgb_name()

    return img


def setup_baked_nodes(tree, root_ch, uv_map, interpolation):
    """Setup baked nodes for a channel.

    Parameters:
        tree: Node tree
        root_ch: Root channel
        uv_map (str): UV map name
        interpolation (str): Interpolation type

    Returns:
        tuple: (baked_node, img_name, filepath)
    """
    baked = tree.nodes.get(root_ch.baked)
    # Check if the baked node is unique per channel
    if not baked or not is_root_ch_prop_node_unique(root_ch, "baked"):
        baked = new_node(
            tree, root_ch, "baked", "ShaderNodeTexImage", "Baked " + root_ch.name
        )

    if hasattr(baked, "color_space"):
        # VALUE channels should use NONE to preserve data
        if (
            root_ch.colorspace == "LINEAR"
            or root_ch.type == "NORMAL"
            or root_ch.type == "VALUE"
        ):
            baked.color_space = "NONE"
        else:
            baked.color_space = "COLOR"

    baked.interpolation = interpolation

    # Normal related nodes
    if root_ch.type == "NORMAL":
        baked_normal = tree.nodes.get(root_ch.baked_normal)
        if not baked_normal:
            baked_normal = new_node(
                tree, root_ch, "baked_normal", "ShaderNodeNormalMap", "Baked Normal"
            )
        baked_normal.uv_map = uv_map

        baked_normal_prep = tree.nodes.get(root_ch.baked_normal_prep)
        if not baked_normal_prep:
            baked_normal_prep = new_node(
                tree,
                root_ch,
                "baked_normal_prep",
                "ShaderNodeGroup",
                "Baked Normal Preparation",
            )
            baked_normal_prep.node_tree = get_node_tree_lib(NORMAL_MAP_PREP_LEGACY)

    # Check if image is available and get name/filepath
    img_name = tree.name + " " + root_ch.name
    filepath = ""

    if baked.image:
        img_name = baked.image.name
        if root_ch.type == "NORMAL":
            filepath = baked.image.filepath
        else:
            filepath = get_valid_filepath(baked.image, False)
        baked.image.name = "____TEMP"

    return baked, img_name, filepath


def get_image_name_and_path(tree, root_ch, segment, img, use_hdr):
    """Get image name and filepath for baking.

    Parameters:
        tree: Node tree
        root_ch: Root channel
        segment: Optional segment
        img: Optional existing image
        use_hdr (bool): Whether using HDR

    Returns:
        tuple: (img_name, filepath)
    """
    if segment:
        return "__TEMP_SEGMENT_", ""
    elif not img:
        return tree.name + " " + root_ch.name, ""
    else:
        return img.name, get_valid_filepath(img, use_hdr)
