# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Core logic for baking all channels and creating a Principled BSDF material.

Creates a new material with baked textures wired to a Principled BSDF,
stores the original material name for revert, and assigns it to the object.
"""

import bpy

from mixar.config.logging_config import get_logger
from ...utils.bsdf_constants import CHANNEL_TO_BSDF_SOCKET
from ...core.io.utils.bsdf_connections import (
    get_bsdf_socket_name,
    get_companion_socket_for_target,
)

logger = get_logger(__name__)

_MIXAR_ORIGINAL_MAT_KEY = "_mixar_original_material"


def create_export_material(obj, mp, tree):
    """Create a Principled BSDF material from baked channel images.

    Iterates through all baked channels, creates texture nodes for each,
    and wires them to the correct BSDF inputs. AO is multiplied with
    Base Color. Normal channels get a Normal Map node.

    Args:
        obj: The active Blender object.
        mp: The MPaint property group.
        tree: The node tree containing baked image nodes.

    Returns:
        The new material, or None on failure.
    """
    original_mat = obj.active_material
    if not original_mat:
        logger.error("No active material on object")
        return None

    # Create new material
    mat_name = f"{original_mat.name}_BakedExport"
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    mat[_MIXAR_ORIGINAL_MAT_KEY] = original_mat.name

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Clear default nodes
    nodes.clear()

    # Create output + Principled BSDF
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (400, 0)

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    # Track what gets connected to Base Color (for AO multiply)
    base_color_node = None
    base_color_output = None
    ao_image_node = None

    x_offset = -300
    y_offset = 300
    node_spacing = 280

    for i, ch in enumerate(mp.channels):
        baked_node = tree.nodes.get(ch.baked)
        if not baked_node or not baked_node.image:
            continue

        socket_name = get_bsdf_socket_name(ch.name)
        is_ao = ch.name in ("Ambient Occlusion", "AO")

        if not socket_name and not is_ao:
            logger.debug(f"Skipping channel '{ch.name}': no BSDF mapping")
            continue

        # Create image texture node
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = baked_node.image
        tex.location = (x_offset, y_offset - i * node_spacing)
        tex.label = ch.name

        if ch.type == "VALUE":
            tex.image.colorspace_settings.name = "Non-Color"

        if is_ao:
            ao_image_node = tex
            continue

        if not socket_name:
            continue

        bsdf_input = bsdf.inputs.get(socket_name)
        if not bsdf_input:
            logger.debug(f"BSDF socket '{socket_name}' not found")
            continue

        if ch.type == "NORMAL":
            _connect_normal(nodes, links, tex, bsdf, bsdf_input)
        else:
            links.new(tex.outputs["Color"], bsdf_input)

        # Track Base Color for AO multiply
        if socket_name == "Base Color":
            base_color_node = tex
            base_color_output = tex.outputs["Color"]

        # Set companion sockets (Emission Strength, etc.)
        companion = get_companion_socket_for_target(socket_name)
        if companion:
            comp_socket = bsdf.inputs.get(companion[0])
            if comp_socket:
                comp_socket.default_value = companion[1]

    # Wire AO as multiply with Base Color
    if ao_image_node and base_color_node:
        _insert_ao_multiply(nodes, links, base_color_node, ao_image_node, bsdf)

    # Assign to object
    slot_idx = obj.active_material_index
    obj.data.materials[slot_idx] = mat

    logger.info(f"Created export material '{mat_name}' on '{obj.name}'")
    return mat


def _connect_normal(nodes, links, tex_node, bsdf, bsdf_input):
    """Insert a Normal Map node between texture and BSDF Normal input."""
    tex_node.image.colorspace_settings.name = "Non-Color"

    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.location = (
        tex_node.location.x + 200,
        tex_node.location.y,
    )

    links.new(tex_node.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], bsdf_input)


def _insert_ao_multiply(nodes, links, base_color_node, ao_node, bsdf):
    """Insert a Multiply mix node between Base Color texture and BSDF.

    Base Color × AO → Base Color input.
    """
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = 'RGBA'
    mix.blend_type = 'MULTIPLY'
    mix.location = (
        base_color_node.location.x + 200,
        base_color_node.location.y - 50,
    )
    # Factor = 1.0 (full AO strength)
    mix.inputs["Factor"].default_value = 1.0

    # Remove existing link from base color to BSDF
    bsdf_input = bsdf.inputs.get("Base Color")
    for link in list(links):
        if link.to_socket == bsdf_input:
            links.remove(link)

    # Wire: Base Color → A, AO → B, Result → BSDF Base Color
    links.new(base_color_node.outputs["Color"], mix.inputs[6])  # A_Color
    links.new(ao_node.outputs["Color"], mix.inputs[7])           # B_Color
    links.new(mix.outputs[2], bsdf_input)                        # Result_Color
