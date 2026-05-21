# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Property and layer/mask utility functions for the paint module."""

from .blender_commons import get_user_preferences


def is_parallax_enabled(root_ch):
    """Check if parallax is enabled for a root channel.

    Args:
        root_ch: Root channel object to check.

    Returns:
        bool: True if parallax is enabled, False otherwise.
    """
    if not root_ch:
        return False

    mp = root_ch.id_data.mp
    mpup = get_user_preferences()

    parallax_enabled = root_ch.enable_parallax if root_ch.type == "NORMAL" else False

    if not mpup.parallax_without_baked and not mp.use_baked:
        parallax_enabled = False

    return parallax_enabled


def is_bump_distance_relevant(layer, ch):
    """Check if bump distance is relevant for a layer and channel.

    Args:
        layer: Layer object to check.
        ch: Channel object to check.

    Returns:
        bool: False if layer type is COLOR/BACKGROUND and transition bump is enabled, True otherwise.
    """
    if layer.type in {"COLOR", "BACKGROUND"} and ch.enable_transition_bump:
        return False
    return True


def is_object_work_with_uv(obj):
    """Check if an object type supports UV mapping.

    Args:
        obj: Blender object to check.

    Returns:
        bool: True if object type is MESH or CURVE, False otherwise.
    """
    return obj.type in {"MESH", "CURVE"}


def load_hemi_props(layer, source):
    """Load hemisphere lighting properties from layer to source node tree.

    Args:
        layer: Layer object containing hemi properties to load.
        source: Source node object with node tree to update.

    Returns:
        None
    """
    norm = source.node_tree.nodes.get("Normal")
    if norm:
        norm.outputs[0].default_value = layer.hemi_vector
    trans = source.node_tree.nodes.get("Vector Transform")
    if trans:
        trans.convert_from = layer.hemi_space


def save_hemi_props(layer, source):
    """Save hemisphere lighting properties from source node tree to layer.

    Args:
        layer: Layer object to save hemi properties to.
        source: Source node object with node tree to read from.

    Returns:
        None
    """
    norm = source.node_tree.nodes.get("Normal")
    if norm:
        layer.hemi_vector = norm.outputs[0].default_value


def is_mesh_flat_shaded(mesh):
    """Check if a mesh uses flat shading (approximate check).

    Note: This is an approximate method that checks only the first 10 polygons for performance.

    Args:
        mesh: Blender mesh object to check.

    Returns:
        bool: True if any polygon in the first 10 doesn't use smooth shading, False otherwise.
    """
    # NOTE: This is just approximate way to know if the mesh is flat shaded or not

    for i, f in enumerate(mesh.polygons):
        if not f.use_smooth:
            return True

        # Only check first 10 polygons to improve performance
        if i > 10:
            break

    return False


def is_mask_using_vector(mask):
    """Check if a mask uses vector data.

    Args:
        mask: Mask object to check.

    Returns:
        bool: True if mask uses baked data or type requires vectors, False otherwise.
    """
    if mask.use_baked or mask.type not in {
        "VCOL",
        "BACKGROUND",
        "COLOR",
        "COLOR_ID",
        "HEMI",
        "OBJECT_INDEX",
        "BACKFACE",
        "EDGE_DETECT",
        "MODIFIER",
        "AO",
    }:
        return True

    return False


def get_channel_index(root_ch):
    """Get the index of a root channel in the channels list.

    Args:
        root_ch: Root channel object to find the index of.

    Returns:
        int: Index of the channel if found, None otherwise.
    """
    mp = root_ch.id_data.mp

    for i, c in enumerate(mp.channels):
        if c == root_ch:
            return i


def get_active_layer_safe(mp):
    """Safely get active layer with bounds checking.

    Args:
        mp: The mixar paint data object containing layers.

    Returns:
        Layer object if active_layer_index is valid, None otherwise.
    """
    if not mp or not mp.layers:
        return None
    if mp.active_layer_index < 0 or mp.active_layer_index >= len(mp.layers):
        return None
    return mp.layers[mp.active_layer_index]


def get_active_mask_safe(layer):
    """Safely get active mask with bounds checking.

    Args:
        layer: The layer object containing masks.

    Returns:
        Mask object if active_mask_index is valid, None otherwise.
    """
    if not layer or not layer.masks:
        return None
    if layer.active_mask_index < 0 or layer.active_mask_index >= len(layer.masks):
        return None
    return layer.masks[layer.active_mask_index]


def get_write_height(ch):
    """Get the write height property from a channel.

    Args:
        ch: Channel object to get write height from.

    Returns:
        The write_height value from the channel.
    """
    # if ch.normal_map_type == 'NORMAL_MAP':
    #    return ch.normal_write_height
    return ch.write_height


def get_first_mirror_modifier(obj):
    """Get the first mirror modifier from an object.

    Args:
        obj: Object to search for mirror modifier.

    Returns:
        Modifier object if found, None otherwise.
    """
    for m in obj.modifiers:
        if m.type == "MIRROR":
            return m

    return None
