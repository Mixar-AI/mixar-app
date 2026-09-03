# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BSDF connection helpers for paint module channels.

Provides functions to connect channel outputs to Principled BSDF inputs.
Targeting Blender 5.0 only.
"""

import bpy

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


def bsdf_socket_driven_by_node(bsdf, socket_name, source_node, max_depth=16):
    """Return True if ``source_node`` transitively drives a BSDF input socket.

    Walks incoming links backward from ``bsdf.inputs[socket_name]``, following any
    intermediate nodes (the AO Multiply mix node, reroutes, math, etc.) until it
    either reaches ``source_node`` or exhausts the graph. Errs toward True: any
    path that reaches ``source_node`` counts as "driven". Bounded depth guards
    against cycles.

    ``source_node`` and ``bsdf`` are expected to live in the same node tree, so
    node identity is compared by (unique-within-tree) name.

    Args:
        bsdf: The Principled BSDF node.
        socket_name: The BSDF input socket to inspect (e.g. "Base Color").
        source_node: The node that should be upstream (the Mixar Paint group node).
        max_depth: Backward-traversal depth limit.

    Returns:
        True if source_node is upstream of the socket, else False.
    """
    if not bsdf or source_node is None:
        return False
    socket = bsdf.inputs.get(socket_name)
    if socket is None:
        return False

    source_name = getattr(source_node, "name", None)
    if not source_name:
        return False

    seen = set()
    # Frontier of (node, depth) reached by walking links backward.
    frontier = [(link.from_node, 0) for link in socket.links if link.from_node]
    while frontier:
        node, depth = frontier.pop()
        if node is None or depth > max_depth:
            continue
        if getattr(node, "name", None) == source_name:
            return True
        key = node.name
        if key in seen:
            continue
        seen.add(key)
        for inp in getattr(node, "inputs", []):
            for link in getattr(inp, "links", []):
                if link.from_node:
                    frontier.append((link.from_node, depth + 1))
    return False


def ensure_group_drives_bsdf(mat, group_node):
    """Ensure the Mixar Paint group actually drives every BSDF socket it outputs.

    Scripted layer CRUD only ever rewires the group's *internal* tree; nothing on
    those paths repairs the material-level link from the group's outputs to the
    Principled BSDF. If that link is missing (never made) or points at a foreign
    source (e.g. an imported model's leftover base-color image texture), the layer
    stack drives nothing visible and the render never changes.

    This relinks ``group_node.outputs[ch] -> bsdf.inputs[socket]`` ONLY when the
    socket is not already driven (directly or transitively) by the group. That
    leaves intentional chains intact — e.g. create_material's Color -> AO Multiply
    -> Base Color still reaches the group, so it is left untouched — while a
    missing or foreign link gets repaired (``links.new`` replaces the stale link).
    Channels the group does not output are never invented.

    Args:
        mat: The material owning both the group node and the BSDF.
        group_node: The Mixar Paint group node.

    Returns:
        List of channel/output names that were (re)linked.
    """
    relinked = []
    if not mat or not mat.node_tree or group_node is None:
        return relinked
    bsdf = find_principled_bsdf(mat)
    if not bsdf:
        return relinked

    for output_socket in group_node.outputs:
        socket_name = get_bsdf_socket_name(output_socket.name)
        if not socket_name:
            continue
        target = bsdf.inputs.get(socket_name)
        if target is None:
            continue
        if bsdf_socket_driven_by_node(bsdf, socket_name, group_node):
            continue  # already driven (directly or via an intermediate) — leave it
        try:
            mat.node_tree.links.new(output_socket, target)
            relinked.append(output_socket.name)
            logger.info(
                "Relinked Mixar group output '%s' to BSDF '%s' (was disconnected)",
                output_socket.name, socket_name,
            )
        except Exception:
            logger.debug(
                "Could not relink group output '%s' to BSDF socket '%s'",
                output_socket.name, socket_name, exc_info=True,
            )
    return relinked


def commit_mp_material(node, mat=None, context=None, relink=True):
    """Flush a scripted Mixar Paint edit so the render reflects it.

    Two things the interactive UI does implicitly but a headless ``EXEC_DEFAULT``
    script path does not:
      1. Repair the group -> BSDF drive links (``ensure_group_drives_bsdf``), so a
         disconnected composite is reconnected.
      2. Tag the group node tree + the material and force a depsgraph re-eval, so
         EEVEE recompiles the GPU material instead of serving a stale shader.

    Mirrors the sibling agent path ``set_paint_layer_parameters`` (which does
    ``node.node_tree.update_tag()`` + ``view_layer.update()``) and is safe to call
    from both operator ``execute`` and plain agent-tool functions.

    Args:
        node: The Mixar Paint group node that was edited.
        mat: The material owning the node (needed for the relink; optional).
        context: Blender context (defaults to ``bpy.context``).
        relink: When True (default) also repair the group -> BSDF links.
    """
    if node is None:
        return
    ctx = context or bpy.context

    if relink and mat is not None:
        try:
            ensure_group_drives_bsdf(mat, node)
        except Exception:
            logger.debug("ensure_group_drives_bsdf failed", exc_info=True)

    try:
        tree = getattr(node, "node_tree", None)
        if tree is not None:
            tree.update_tag()
    except Exception:
        pass
    try:
        if mat is not None:
            mat.update_tag()
    except Exception:
        pass
    try:
        view_layer = getattr(ctx, "view_layer", None)
        if view_layer is not None:
            view_layer.update()
    except Exception:
        pass
