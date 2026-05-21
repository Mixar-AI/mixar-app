# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BSDF connection helpers for paint module channels.

Provides functions to connect channel outputs to Principled BSDF inputs.
Targeting Blender 5.0 only.
"""

from ......config.logging_config import get_logger
from ....utils.blender_commons import get_active_material
from ....utils.bsdf_constants import (
    CHANNEL_TO_BSDF_SOCKET,
    BSDF_COMPANION_PREFIXES,
    BSDF_COMPANION_SUFFIX_MAP,
    CHANNEL_DEFAULT_VALUES,
)

logger = get_logger(__name__)


def get_bsdf_socket_name(channel_name):
    """Get the Principled BSDF socket name for a channel.

    Args:
        channel_name: The name of the channel.

    Returns:
        The socket name to use, or None if no mapping exists.
    """
    return CHANNEL_TO_BSDF_SOCKET.get(channel_name)


def find_principled_bsdf(mat):
    """Find the Principled BSDF node in a material.

    Args:
        mat: The Blender material to search.

    Returns:
        The Principled BSDF node, or None if not found.
    """
    if not mat or not mat.node_tree:
        return None

    for node in mat.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node

    return None


def connect_channel_to_bsdf(mat, group_node, channel):
    """Connect a channel output to the corresponding BSDF input.

    Args:
        mat: The Blender material.
        group_node: The Mixar group node.
        channel: The channel to connect.

    Returns:
        The target socket name if connection was made, None otherwise.
    """
    if not mat or not mat.node_tree:
        return None

    bsdf = find_principled_bsdf(mat)
    if not bsdf:
        logger.debug("No Principled BSDF found in material")
        return None

    socket_name = get_bsdf_socket_name(channel.name)
    if not socket_name:
        logger.debug(f"No BSDF socket mapping for channel '{channel.name}'")
        return None

    # Get the BSDF socket
    socket = bsdf.inputs.get(socket_name)
    if not socket:
        logger.debug(f"BSDF socket '{socket_name}' not found")
        return None

    # Check if the group node has an output for this channel
    output_socket = group_node.outputs.get(channel.name)
    if not output_socket:
        logger.debug(f"Group node output '{channel.name}' not found")
        return None

    # Connect
    try:
        mat.node_tree.links.new(output_socket, socket)
        logger.info(f"Connected channel '{channel.name}' to BSDF socket '{socket_name}'")
        return socket_name  # Return target socket name for companion socket setup
    except Exception as e:
        logger.error(f"Failed to connect channel: {e}")
        return None


def get_companion_socket_for_target(target_socket_name):
    """Get companion socket that needs to be enabled for target socket to have effect.

    Based on Mixar Paint bake_common.py pattern:
    - Sockets starting with 'Subsurface' need 'Subsurface Weight' > 0
    - Sockets starting with 'Coat' need 'Coat Weight' > 0
    - Sockets starting with 'Sheen' need 'Sheen Weight' > 0
    - Sockets starting with 'Emission' need 'Emission Strength' > 0

    Args:
        target_socket_name: The name of the BSDF socket being connected to.

    Returns:
        Tuple of (companion_socket_name, value) or None if no companion needed.
    """
    for prefix in BSDF_COMPANION_PREFIXES:
        if target_socket_name.startswith(prefix):
            companion_socket_name = BSDF_COMPANION_SUFFIX_MAP[prefix]

            # Don't set companion if we're connecting to the weight/strength socket itself
            if target_socket_name == companion_socket_name:
                return None

            return (companion_socket_name, 1.0)

    return None


def setup_bsdf_companion_socket(mat, target_socket_name, set_value=True):
    """Set up companion socket for target sockets that need it.

    For sockets like Emission Color, Sheen Tint, Coat Roughness etc.,
    the corresponding weight/strength socket defaults to 0.0, effectively
    disabling the effect. This function sets those companion sockets to 1.0.

    Args:
        mat: The Blender material.
        target_socket_name: The name of the BSDF socket being connected to.
        set_value: Whether to actually set the value (controlled by UI option).

    Returns:
        True if a companion socket was found and handled, False otherwise.
    """
    companion_info = get_companion_socket_for_target(target_socket_name)
    if not companion_info:
        return False

    socket_name, default_value = companion_info

    bsdf = find_principled_bsdf(mat)
    if not bsdf:
        return False

    socket = bsdf.inputs.get(socket_name)
    if not socket:
        logger.debug(f"Companion socket '{socket_name}' not found")
        return False

    if set_value:
        socket.default_value = default_value
        logger.info(f"Set BSDF socket '{socket_name}' to {default_value}")

    return True


def get_channel_default_value(channel_name, channel_type):
    """Get the default value for a channel, considering BSDF requirements.

    Args:
        channel_name: The name of the channel.
        channel_type: The type of channel (RGB, VALUE, NORMAL).

    Returns:
        The default value to use, or None to use standard defaults.
    """
    return CHANNEL_DEFAULT_VALUES.get(channel_name)


def needs_strength_setting(channel_name):
    """Check if a channel needs the 'set strength to 1' option.

    Uses the channel-to-socket mapping to determine if the target socket
    would benefit from having its companion weight/strength socket enabled.

    Args:
        channel_name: The name of the channel.

    Returns:
        True if the channel benefits from setting companion socket strength.
    """
    target_socket = CHANNEL_TO_BSDF_SOCKET.get(channel_name)
    if not target_socket:
        return False

    return get_companion_socket_for_target(target_socket) is not None
