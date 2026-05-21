# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection channel processing.

This module handles group channel, source type, procedural channel,
and modifier processing for layer node reconnection.
"""

from typing import TYPE_CHECKING, Any, Tuple

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....utils.common import get_entity_input_name
from ....utils.constants import ONE_VALUE, TREE_START, io_suffix
from ..utils.io_utils import create_link
from ...node.node_utils import get_essential_node

if TYPE_CHECKING:
    from .layer_connections_context import LayerConnectionContext


def process_group_channel(
    ctx: "LayerConnectionContext", ch, root_ch, source, rgb: Any, alpha: Any
) -> Tuple[Any, Any, Any, Any]:
    """Process GROUP layer channel outputs.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        source: The source node.
        rgb: Current RGB value.
        alpha: Current alpha value.

    Returns:
        Tuple of (rgb, alpha, group_vdisp, vdisp_alpha).
    """
    layer = ctx.layer
    tree = ctx.tree

    group_vdisp = None
    vdisp_alpha = None

    if not source:
        return rgb, alpha, group_vdisp, vdisp_alpha

    if root_ch.type == "NORMAL" and ch.enable_transition_bump:
        group_height = source.outputs.get(
            root_ch.name + io_suffix["HEIGHT"] + io_suffix["GROUP"]
        )
        if group_height:
            rgb = group_height
    else:
        group_channel = source.outputs.get(root_ch.name + io_suffix["GROUP"])
        if group_channel:
            rgb = group_channel

    if root_ch.type == "NORMAL":
        group_height_alpha = source.outputs.get(
            root_ch.name + io_suffix["HEIGHT"] + io_suffix["ALPHA"] + io_suffix["GROUP"]
        )
        if group_height_alpha:
            alpha = group_height_alpha
    else:
        group_channel_alpha = source.outputs.get(
            root_ch.name + io_suffix["ALPHA"] + io_suffix["GROUP"]
        )
        if group_channel_alpha:
            alpha = group_channel_alpha

    # Vector displacement from group
    group_vdisp = source.outputs.get(
        root_ch.name + io_suffix["VDISP"] + io_suffix["GROUP"]
    )
    vdisp_alpha = source.outputs.get(
        root_ch.name + io_suffix["VDISP"] + io_suffix["ALPHA"] + io_suffix["GROUP"]
    )

    return rgb, alpha, group_vdisp, vdisp_alpha


def process_channel_source_type(
    ctx: "LayerConnectionContext",
    layer,
    ch,
    root_ch,
    rgb: Any,
    alpha: Any,
    start_rgb_1: Any,
    start_alpha_1: Any,
) -> Tuple[Any, Any, int]:
    """Process RGB/alpha based on layer source type.

    Args:
        ctx: The LayerConnectionContext.
        layer: The layer object.
        ch: The layer channel.
        root_ch: The root channel.
        rgb: Current RGB value.
        alpha: Current alpha value.
        start_rgb_1: Secondary RGB start value.
        start_alpha_1: Secondary alpha start value.

    Returns:
        Tuple of (rgb, alpha, source_index).
    """
    tree = ctx.tree
    source_index = 0

    # Handle PROCEDURAL layers
    if layer.type == "PROCEDURAL":
        rgb, alpha = process_procedural_channel(ctx, ch, root_ch, rgb, alpha)

    elif not layer.use_baked and layer.type not in {
        "IMAGE", "VCOL", "BACKGROUND", "COLOR", "HEMI",
        "OBJECT_INDEX", "MUSGRAVE", "EDGE_DETECT", "AO",
    }:
        # Noise and voronoi output has flipped order since Blender 2.81
        if (
            layer.type == "NOISE"
            or (
                layer.type == "VORONOI"
                and layer.voronoi_feature not in {"DISTANCE_TO_EDGE", "N_SPHERE_RADIUS"}
            )
        ):
            if ch.layer_input == "RGB":
                rgb = start_rgb_1
                alpha = start_alpha_1
                source_index = 2
        elif ch.layer_input == "ALPHA":
            rgb = start_rgb_1
            alpha = start_alpha_1
            source_index = 2

    return rgb, alpha, source_index


def process_procedural_channel(
    ctx: "LayerConnectionContext", ch, root_ch, rgb: Any, alpha: Any
) -> Tuple[Any, Any]:
    """Process PROCEDURAL layer channel outputs.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel (for accessing normal_map_type).
        root_ch: The root channel.
        rgb: Current RGB value.
        alpha: Current alpha value.

    Returns:
        Tuple of (rgb, alpha).
    """
    tree = ctx.tree
    source = ctx.source

    # Map channel names to procedural material output socket names.
    # Channels not in this map fall back to using root_ch.name directly,
    # allowing dynamically added channels to pick up matching outputs.
    # Core channels (Color, Metallic, Roughness, Normal, Height, Alpha)
    # flow through the full channel pipeline. Additional entries here act
    # as a safety net if these channels are ever enabled in the system.
    channel_output_map = {
        # Core channels
        "Color": "Base Color",
        "Metallic": "Metallic",
        "Roughness": "Roughness",
        "Normal": "Normal",
        "Height": "Height",
        "Alpha": "Alpha",
        # Extended PBR channels — channel name → procedural output name
        "Ambient Occlusion": "AO",
        "Emission": "Emission Color",
        "Emission Color": "Emission Color",
        "Emission Strength": "Emission Strength",
        "Subsurface": "Subsurface Weight",
        "Subsurface Weight": "Subsurface Weight",
        "Clearcoat": "Coat Weight",
        "Coat": "Coat Weight",
        "Coat Weight": "Coat Weight",
        "Clearcoat Roughness": "Coat Roughness",
        "Coat Roughness": "Coat Roughness",
        "Coat Tint": "Coat Tint",
        "Clearcoat Normal": "Coat Normal",
        "Coat Normal": "Coat Normal",
        "Sheen": "Sheen Weight",
        "Sheen Weight": "Sheen Weight",
        "Sheen Roughness": "Sheen Roughness",
        "Sheen Tint": "Sheen Tint",
        "Anisotropic": "Anisotropic",
        "Anisotropic Rotation": "Anisotropic Rotation",
        "Specular": "Specular IOR Level",
        "Specular IOR Level": "Specular IOR Level",
        "Specular Tint": "Specular Tint",
        "Transmission": "Transmission Weight",
        "Transmission Weight": "Transmission Weight",
        "IOR": "IOR",
        "Coat IOR": "Coat IOR",
        "Subsurface Scale": "Subsurface Scale",
        "Subsurface Anisotropy": "Subsurface Anisotropy",
    }

    output_name = channel_output_map.get(root_ch.name, root_ch.name)

    # Special handling for Normal channel based on normal_map_type
    if root_ch.name == "Normal" and source:
        normal_map_type = getattr(ch, 'normal_map_type', 'BUMP_MAP')
        if normal_map_type == 'BUMP_MAP':
            # For BUMP_MAP, prefer Height output for bump calculation
            if "Height" in source.outputs:
                rgb = source.outputs["Height"]
                alpha = get_essential_node(tree, ONE_VALUE)[0]
                return rgb, alpha
            # No Height output - keep original rgb
            return rgb, alpha
        elif normal_map_type == 'BUMP_NORMAL_MAP':
            # For BUMP_NORMAL_MAP, use Height output for bump source (rgb)
            # The secondary normal source (normal) is handled separately via
            # process_normal_override or by reading the "Normal" output
            if "Height" in source.outputs:
                rgb = source.outputs["Height"]
                alpha = get_essential_node(tree, ONE_VALUE)[0]
                return rgb, alpha
            return rgb, alpha

    if output_name and source and output_name in source.outputs:
        rgb = source.outputs[output_name]
        # For non-Color channels, set alpha to 1.0 (full opacity) since
        # these channels represent data values, not paintable RGBA
        if root_ch.type != "RGB" or root_ch.name != "Color":
            alpha = get_essential_node(tree, ONE_VALUE)[0]

    return rgb, alpha


def connect_intensity_multiplier(
    ctx: "LayerConnectionContext", ch, intensity_multiplier
) -> None:
    """Connect intensity multiplier node.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        intensity_multiplier: The intensity multiplier node.
    """
    tree = ctx.tree
    trans_bump_ch = ctx.trans_bump_ch
    trans_bump_flip = ctx.trans_bump_flip
    tb_value = ctx.tb_value
    tb_second_value = ctx.tb_second_value

    ch_tb_fac = get_essential_node(tree, TREE_START).get(
        get_entity_input_name(ch, "transition_bump_fac")
    )

    if intensity_multiplier and ch != trans_bump_ch:
        if trans_bump_flip:
            if tb_second_value:
                create_link(tree, tb_second_value, intensity_multiplier.inputs["Multiplier"])
        elif tb_value:
            create_link(tree, tb_value, intensity_multiplier.inputs["Multiplier"])

        if ch_tb_fac:
            create_link(tree, ch_tb_fac, intensity_multiplier.inputs["Factor"])


def process_group_normal_channel(
    ctx: "LayerConnectionContext", ch, root_ch, source, normal: Any
) -> Tuple[Any, Any]:
    """Process GROUP layer normal channel.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        source: The source node.
        normal: Current normal value.

    Returns:
        Tuple of (normal, normal_alpha).
    """
    normal_alpha = None

    if source and root_ch.name + io_suffix["GROUP"] in source.outputs:
        normal = source.outputs.get(root_ch.name + io_suffix["GROUP"])

    if source and root_ch.name + io_suffix["ALPHA"] + io_suffix["GROUP"] in source.outputs:
        normal_alpha = source.outputs.get(
            root_ch.name + io_suffix["ALPHA"] + io_suffix["GROUP"]
        )

    return normal, normal_alpha


def process_channel_modifiers(
    ctx: "LayerConnectionContext", ch, root_ch, mod_group, rgb: Any, alpha: Any
) -> Tuple[Any, Any]:
    """Process channel modifiers.

    Args:
        ctx: The LayerConnectionContext.
        ch: The layer channel.
        root_ch: The root channel.
        mod_group: The modifier group node.
        rgb: Current RGB value.
        alpha: Current alpha value.

    Returns:
        Tuple of (rgb, alpha).
    """
    from ...element.modifier_utils import reconnect_all_modifier_nodes

    tree = ctx.tree

    rgb, alpha = reconnect_all_modifier_nodes(tree, ch, rgb, alpha, mod_group)

    return rgb, alpha
