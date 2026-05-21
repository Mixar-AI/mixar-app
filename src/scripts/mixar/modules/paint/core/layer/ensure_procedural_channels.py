# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auto-create channels for procedural layer outputs.

When a PROCEDURAL layer is added, this module inspects the node group's
outputs and creates any missing channels in the Mixar Paint system.
This ensures all procedural outputs flow through the full channel pipeline
with blend modes, opacity, and masks.
"""

from .....config.logging_config import get_logger
from .create_channels import create_new_mp_channel
from .channel_io import check_all_channel_ios
from ..io.connections.layer_connections import reconnect_mp_nodes
from ..io.arrangements.layer_arrangements import rearrange_mp_nodes
from ..io.utils.bsdf_connections import (
    connect_channel_to_bsdf,
    setup_bsdf_companion_socket,
    needs_strength_setting,
)
from ..node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import get_active_material

logger = get_logger(__name__)

# Procedural output socket name -> (channel_name, channel_type, non_color,
#                                    connect_to_bsdf, set_strength_to_one)
# Matches the presets in channel_menu.py.
# None means the output is handled elsewhere (Height via Normal/BUMP_MAP,
# Alpha via the alpha mechanism).
PROCEDURAL_OUTPUT_TO_CHANNEL = {
    # Core channels (usually already exist at material creation)
    "Base Color": ("Color", "RGB", False, True, False),
    "Metallic": ("Metallic", "VALUE", True, True, False),
    "Roughness": ("Roughness", "VALUE", True, True, False),
    "Normal": ("Normal", "NORMAL", True, True, False),
    "Height": None,
    "Alpha": None,
    # Extended PBR channels
    "Emission Color": ("Emission", "RGB", False, True, True),
    "Emission Strength": ("Emission Strength", "VALUE", True, True, False),
    "AO": ("Ambient Occlusion", "RGB", True, False, False),
    "Subsurface Weight": ("Subsurface", "VALUE", True, True, False),
    "Coat Weight": ("Clearcoat", "VALUE", True, True, False),
    "Coat Roughness": ("Clearcoat Roughness", "VALUE", True, True, True),
    "Coat Tint": ("Coat Tint", "RGB", False, True, True),  # sRGB — artist-facing color
    "Coat Normal": ("Clearcoat Normal", "NORMAL", True, True, True),
    "Coat IOR": ("Coat IOR", "VALUE", True, True, False),
    "Sheen Weight": ("Sheen", "VALUE", True, True, False),
    "Sheen Roughness": ("Sheen Roughness", "VALUE", True, True, True),
    "Sheen Tint": ("Sheen Tint", "RGB", False, True, True),  # RGB color, sRGB
    "Anisotropic": ("Anisotropic", "VALUE", True, True, False),
    "Anisotropic Rotation": ("Anisotropic Rotation", "VALUE", True, True, False),
    "Specular IOR Level": ("Specular", "VALUE", True, True, False),
    "Specular Tint": ("Specular Tint", "VALUE", True, True, False),
    "Transmission Weight": ("Transmission", "VALUE", True, True, False),
    "IOR": ("IOR", "VALUE", True, True, False),
    "Subsurface Scale": ("Subsurface Scale", "VALUE", True, True, False),
    "Subsurface Anisotropy": ("Subsurface Anisotropy", "VALUE", True, True, False),
}


def get_node_group_output_names(node_group):
    """Get output socket names from a node group interface.

    Args:
        node_group: A ShaderNodeTree.

    Returns:
        Set of output socket names.
    """
    names = set()
    if not node_group or not hasattr(node_group, 'interface'):
        return names
    if hasattr(node_group.interface, 'items_tree'):
        for item in node_group.interface.items_tree:
            if hasattr(item, 'in_out') and item.in_out == 'OUTPUT':
                names.add(item.name)
    return names


def ensure_channels_for_procedural(tree, mp, node_group):
    """Create missing channels for a procedural layer's outputs.

    Inspects the node group's output sockets and creates any channels
    that don't already exist in the Mixar Paint system. Each new channel
    is wired to the corresponding Principled BSDF input.

    This must be called BEFORE the procedural layer is created, so the
    layer picks up all channels during creation.

    Args:
        tree: The Mixar Paint group tree (node.node_tree).
        mp: The Mixar Paint property group (tree.mp).
        node_group: The procedural material's ShaderNodeTree.

    Returns:
        List of newly created channel names.
    """
    output_names = get_node_group_output_names(node_group)
    if not output_names:
        return []

    existing_channels = {ch.name for ch in mp.channels}

    # Collect channels that need to be created
    channels_to_create = []
    for output_name in output_names:
        channel_info = PROCEDURAL_OUTPUT_TO_CHANNEL.get(output_name)
        if channel_info is None:
            continue

        ch_name, ch_type, non_color, connect_to_bsdf, set_strength = channel_info
        if ch_name not in existing_channels:
            channels_to_create.append(
                (ch_name, ch_type, non_color, connect_to_bsdf, set_strength)
            )

    if not channels_to_create:
        return []

    node = get_active_mpaint_node()
    mat = get_active_material()

    # Create all channels in a single halt_reconnect block
    created = []
    mp.halt_reconnect = True
    try:
        for ch_name, ch_type, non_color, connect_to_bsdf, set_strength in channels_to_create:
            channel = create_new_mp_channel(
                tree, ch_name, ch_type, non_color=non_color, enable=False
            )
            created.append((channel, connect_to_bsdf, set_strength))
            logger.info(f"Created channel '{ch_name}' ({ch_type}) for procedural output")
    finally:
        mp.halt_reconnect = False

    # Create I/O sockets, reconnect, and rearrange
    check_all_channel_ios(mp, reconnect=False)
    reconnect_mp_nodes(tree)
    rearrange_mp_nodes(tree)

    # Wire new channels to BSDF
    if mat and node:
        for channel, connect_to_bsdf, set_strength in created:
            if connect_to_bsdf:
                target_socket = connect_channel_to_bsdf(mat, node, channel)
                if target_socket and set_strength:
                    setup_bsdf_companion_socket(mat, target_socket)

    channel_names = [ch.name for ch, _, _ in created]
    logger.info(
        f"Created {len(channel_names)} channels for procedural material: "
        f"{channel_names}"
    )
    return channel_names
