# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection normal height - coordinator module.

This module re-exports functions for handling height processor and blend
connections in normal channel processing from the layer_connections_height
submodule.

Submodules:
- layer_connections_height: Height processor and blend connection functions
"""

# Re-export all height-related functions
from .layer_connections_height import (
    connect_height_blend_smooth_bump,
    connect_height_blend_standard,
    connect_height_blend_to_normal_proc,
    connect_height_proc_parameters,
    connect_height_proc_to_normal_proc,
    connect_height_proc_value_inputs,
    connect_max_height_calc,
    connect_smooth_bump_height_outputs,
    get_blend_alpha_output,
    get_height_alpha_output,
)

# Normal-related functions (inline for backward compatibility)
from ......config.logging_config import get_logger
from ....utils.constants import GEOMETRY, TREE_START, io_suffix
from ..utils.io_utils import create_link
from ...node.node_utils import get_essential_node

logger = get_logger(__name__)


def connect_normal_map_proc_input(tree, ch, rgb, normal, normal_map_proc):
    """Connect painted texture to normal map processor input.

    For NORMAL_MAP mode: rgb (painted normal map) -> normal_map_proc.inputs['Color']
    For BUMP_NORMAL_MAP mode: normal (secondary source) -> normal_map_proc.inputs['Color']
    Also connects normal_strength to Strength input.

    Args:
        tree: The node tree.
        ch: The layer channel.
        rgb: RGB source (primary painted texture, used for NORMAL_MAP mode).
        normal: Normal source (secondary painted texture, used for BUMP_NORMAL_MAP mode).
        normal_map_proc: Normal map processor node (ShaderNodeNormalMap).
    """
    if not normal_map_proc or 'Color' not in normal_map_proc.inputs:
        return

    if ch.normal_map_type == "NORMAL_MAP":
        if rgb:
            create_link(tree, rgb, normal_map_proc.inputs['Color'])
            logger.debug(f"  NORMAL_MAP: Connected rgb -> normal_map_proc.inputs['Color']")
    elif ch.normal_map_type == "BUMP_NORMAL_MAP":
        if normal:
            create_link(tree, normal, normal_map_proc.inputs['Color'])
            logger.debug(f"  BUMP_NORMAL_MAP: Connected normal -> normal_map_proc.inputs['Color']")

    if 'Strength' in normal_map_proc.inputs:
        from ....utils.common import get_entity_input_name
        from ....utils.constants import TREE_START
        ch_normal_strength = get_essential_node(tree, TREE_START).get(
            get_entity_input_name(ch, 'normal_strength')
        )
        if ch_normal_strength:
            create_link(tree, ch_normal_strength, normal_map_proc.inputs['Strength'])
            logger.debug(f"  Connected normal_strength -> normal_map_proc.inputs['Strength']")


def connect_normal_proc_input(
    tree, nodes, layer, ch, root_ch, source, rgb, normal,
    normal_proc, normal_map_proc, height_proc
):
    """Connect normal input to normal processor based on layer type.

    Args:
        tree: The node tree.
        nodes: Node tree nodes.
        layer: The layer object.
        ch: The layer channel.
        root_ch: The root channel.
        source: The source node.
        rgb: RGB source (primary painted texture).
        normal: Normal map value (secondary source for BUMP_NORMAL_MAP).
        normal_proc: Normal processor node.
        normal_map_proc: Normal map processor node.
        height_proc: Height processor node.
    """
    if layer.type not in {"GROUP", "PROCEDURAL"}:
        connect_normal_map_proc_input(tree, ch, rgb, normal, normal_map_proc)

    if layer.type == "GROUP":
        if normal_proc and 'Normal' in normal_proc.inputs:
            create_link(tree, normal, normal_proc.inputs['Normal'])
            logger.debug(f"  GROUP: Connected normal -> normal_proc.inputs['Normal']")

        if source:
            height_group = source.outputs.get(root_ch.name + io_suffix["HEIGHT"] + io_suffix["GROUP"])
            if height_proc and height_group and 'Height' in height_proc.inputs:
                create_link(tree, height_group, height_proc.inputs['Height'])

            if height_proc and root_ch.enable_smooth_bump:
                rgb_n = source.outputs.get(root_ch.name + io_suffix["HEIGHT_N"] + io_suffix["GROUP"])
                rgb_s = source.outputs.get(root_ch.name + io_suffix["HEIGHT_S"] + io_suffix["GROUP"])
                rgb_e = source.outputs.get(root_ch.name + io_suffix["HEIGHT_E"] + io_suffix["GROUP"])
                rgb_w = source.outputs.get(root_ch.name + io_suffix["HEIGHT_W"] + io_suffix["GROUP"])

                if rgb_n and 'Height n' in height_proc.inputs:
                    create_link(tree, rgb_n, height_proc.inputs['Height n'])
                if rgb_s and 'Height s' in height_proc.inputs:
                    create_link(tree, rgb_s, height_proc.inputs['Height s'])
                if rgb_e and 'Height e' in height_proc.inputs:
                    create_link(tree, rgb_e, height_proc.inputs['Height e'])
                if rgb_w and 'Height w' in height_proc.inputs:
                    create_link(tree, rgb_w, height_proc.inputs['Height w'])

    elif layer.type == "PROCEDURAL":
        has_procedural_normal = source and 'Normal' in source.outputs

        if has_procedural_normal and normal_proc and 'Normal' in normal_proc.inputs:
            create_link(tree, source.outputs['Normal'], normal_proc.inputs['Normal'])
            logger.debug(f"  PROCEDURAL: Connected source.outputs['Normal'] -> normal_proc.inputs['Normal']")
        elif normal_proc and 'Normal' in normal_proc.inputs:
            geometry_node = get_essential_node(tree, GEOMETRY)
            if geometry_node and 'Normal' in geometry_node:
                create_link(tree, geometry_node['Normal'], normal_proc.inputs['Normal'])
                logger.debug(f"  PROCEDURAL fallback: Connected geometry Normal -> normal_proc.inputs['Normal']")

    elif normal_map_proc and normal_proc and 'Normal' in normal_proc.inputs:
        create_link(tree, normal_map_proc.outputs[0], normal_proc.inputs['Normal'])
        logger.debug(f"  Connected normal_map_proc -> normal_proc.inputs['Normal']")

    elif normal_proc and 'Normal' in normal_proc.inputs:
        geometry_node = get_essential_node(tree, GEOMETRY)
        if geometry_node and 'Normal' in geometry_node:
            create_link(tree, geometry_node['Normal'], normal_proc.inputs['Normal'])
            logger.debug(f"  BUMP_MAP: Connected geometry Normal -> normal_proc.inputs['Normal']")


def determine_final_rgb_output(
    tree, layer, ch, root_ch, rgb, normal_proc, normal_map_proc, write_height
):
    """Determine the final RGB output based on processor availability and settings.

    Args:
        tree: The node tree.
        layer: The layer object.
        ch: The layer channel.
        root_ch: The root channel.
        rgb: Current RGB value.
        normal_proc: Normal processor node.
        normal_map_proc: Normal map processor node.
        write_height: Whether height writing is enabled.

    Returns:
        The final RGB output socket.
    """
    if normal_map_proc and ch.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'}:
        rgb = normal_map_proc.outputs[0]
        logger.debug(f"  Using normal_map_proc output as rgb")

    if normal_proc and (ch.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'} or layer.type == 'GROUP') and not write_height:
        rgb = normal_proc.outputs[0]
        logger.debug(f"  Using normal_proc output as rgb (BUMP_MAP/GROUP with write_height=False)")

    if not normal_map_proc and not normal_proc and ch.normal_map_type != 'VECTOR_DISPLACEMENT_MAP':
        geometry_node = get_essential_node(tree, GEOMETRY)
        if geometry_node and 'Normal' in geometry_node:
            rgb = geometry_node['Normal']
            logger.debug(f"  Using geometry Normal as rgb (no processors available)")

    # Connect normal_flip (Bump to Normal) only when write_height is FALSE
    # This follows ucupaint pattern - normal_flip is not used when write_height is TRUE
    if not root_ch.enable_smooth_bump and not write_height:
        nodes = tree.nodes
        normal_flip = nodes.get(ch.normal_flip) if hasattr(ch, 'normal_flip') else None
        if normal_flip:
            # Get tangent/bitangent for normal_flip
            uv_name = getattr(layer, 'uv_name', None) or getattr(root_ch, 'main_uv', None)
            if uv_name and 'Tangent' in normal_flip.inputs:
                tangent = get_essential_node(tree, TREE_START).get(uv_name + io_suffix['TANGENT'])
                bitangent = get_essential_node(tree, TREE_START).get(uv_name + io_suffix['BITANGENT'])
                if tangent:
                    create_link(tree, tangent, normal_flip.inputs['Tangent'])
                if bitangent and 'Bitangent' in normal_flip.inputs:
                    create_link(tree, bitangent, normal_flip.inputs['Bitangent'])

            # Connect rgb through normal_flip
            rgb = create_link(tree, rgb, normal_flip.inputs[0])[0]
            logger.debug(f"  Connected rgb through normal_flip (write_height=False)")

    return rgb


def connect_normal_proc_parameters(
    tree, layer, ch, root_ch, normal_proc, normal_map_proc,
    ch_intensity, ch_normal_strength, alpha, normal_alpha
):
    """Connect parameter inputs to normal processor.

    This connects:
    - Intensity to normal_proc
    - Strength to normal_proc and normal_map_proc
    - Alpha to normal_proc
    - Normal Alpha to normal_proc
    - Tangent/Bitangent to normal_proc

    Args:
        tree: The node tree.
        layer: The layer object.
        ch: The layer channel.
        root_ch: The root channel.
        normal_proc: Normal processor node.
        normal_map_proc: Normal map processor node.
        ch_intensity: Channel intensity socket.
        ch_normal_strength: Channel normal strength socket.
        alpha: Alpha socket.
        normal_alpha: Normal alpha socket.
    """
    # Connect intensity to normal_proc
    if ch_intensity and normal_proc and 'Intensity' in normal_proc.inputs:
        create_link(tree, ch_intensity, normal_proc.inputs['Intensity'])
        logger.debug(f"  Connected ch_intensity -> normal_proc.inputs['Intensity']")

    # Connect strength to normal_proc
    if ch_normal_strength and normal_proc and 'Strength' in normal_proc.inputs:
        create_link(tree, ch_normal_strength, normal_proc.inputs['Strength'])
        logger.debug(f"  Connected ch_normal_strength -> normal_proc.inputs['Strength']")

    # Connect alpha to normal_proc
    if alpha and normal_proc and 'Alpha' in normal_proc.inputs:
        create_link(tree, alpha, normal_proc.inputs['Alpha'])
        logger.debug(f"  Connected alpha -> normal_proc.inputs['Alpha']")

    # Connect normal_alpha to normal_proc
    if normal_alpha and normal_proc and 'Normal Alpha' in normal_proc.inputs:
        create_link(tree, normal_alpha, normal_proc.inputs['Normal Alpha'])
        logger.debug(f"  Connected normal_alpha -> normal_proc.inputs['Normal Alpha']")

    # Connect tangent and bitangent to normal_proc
    if normal_proc and 'Tangent' in normal_proc.inputs:
        # Get tangent/bitangent from TREE_START based on layer UV
        uv_name = getattr(layer, 'uv_name', None) or getattr(root_ch, 'main_uv', None)
        if uv_name:
            tangent = get_essential_node(tree, TREE_START).get(uv_name + io_suffix['TANGENT'])
            bitangent = get_essential_node(tree, TREE_START).get(uv_name + io_suffix['BITANGENT'])

            if tangent:
                create_link(tree, tangent, normal_proc.inputs['Tangent'])
                logger.debug(f"  Connected tangent -> normal_proc.inputs['Tangent']")
            if bitangent and 'Bitangent' in normal_proc.inputs:
                create_link(tree, bitangent, normal_proc.inputs['Bitangent'])
                logger.debug(f"  Connected bitangent -> normal_proc.inputs['Bitangent']")


# Define __all__ for explicit exports
__all__ = [
    # Height-related functions (from layer_connections_height)
    'connect_height_proc_value_inputs',
    'connect_height_proc_parameters',
    'get_height_alpha_output',
    'get_blend_alpha_output',
    'connect_height_blend_standard',
    'connect_height_blend_smooth_bump',
    'connect_smooth_bump_height_outputs',
    'connect_height_blend_to_normal_proc',
    'connect_height_proc_to_normal_proc',
    # Normal-related functions (inline)
    'connect_normal_map_proc_input',
    'connect_normal_proc_input',
    'connect_normal_proc_parameters',
    'determine_final_rgb_output',
]
