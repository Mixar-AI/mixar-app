# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update callback functions for layer properties.

This module contains all update callback functions used by layer property groups.
These are separated to keep the main property definitions clean and maintainable.
"""

# Wrapper functions for delayed imports to avoid circular dependency
# The actual implementations are in layer_ui_helpers, but importing at module level
# causes circular imports with the bootstrap loading order


def update_layer_channel_override(self, context):
    """Wrapper that delays import to avoid circular dependency."""
    from ..layer import update_layer_channel_override as _impl
    return _impl(self, context)


def update_layer_channel_override_1(self, context):
    """Wrapper that delays import to avoid circular dependency."""
    from ..layer import update_layer_channel_override_1 as _impl
    return _impl(self, context)


def update_layer_channel_override_vcol_name(self, context):
    """Wrapper that delays import to avoid circular dependency."""
    from ..layer import update_layer_channel_override_vcol_name as _impl
    return _impl(self, context)


def get_parent_layer_from_channel(channel, context):
    """Helper to get the parent MixarLayer from a MixarLayerChannel.

    Returns:
        tuple: (layer, layer_index) or (None, -1) if not found
    """
    scene = context.scene

    # Search through all layers to find which one owns this channel
    for layer_idx, layer in enumerate(scene.mixar_layers):
        for ch in layer.channels:
            if ch == channel:
                return (layer, layer_idx)

    return (None, -1)


def _get_mixar_group_node(context):
    """Helper to find the Mixar Layers group node.

    Returns:
        tuple: (mixar_group_node, material) or (None, None) if not found
    """
    obj = context.active_object
    if not obj or not obj.active_material:
        return (None, None)

    mat = obj.active_material
    if not mat.use_nodes:
        return (None, None)

    # Find the Mixar Layers group node
    for node in mat.node_tree.nodes:
        if (
            node.type == "GROUP"
            and node.node_tree
            and hasattr(node.node_tree, "mixar_mp")
        ):
            if node.node_tree.mixar_mp.is_mixar_node:
                return (node, mat)

    return (None, None)


def _get_layer_tree(context, ui_layer):
    """Helper to get the layer's node tree.

    Args:
        context: Blender context
        ui_layer: The UI layer to get the tree for

    Returns:
        node tree or None if not found
    """
    mixar_group, _ = _get_mixar_group_node(context)
    if not mixar_group:
        return None

    # Get the layer's node tree using the stored group node name
    layer_group = mixar_group.node_tree.nodes.get(ui_layer.mixar_group_node)
    if not layer_group or layer_group.type != "GROUP":
        return None

    return layer_group.node_tree


def _is_update_halted(context, layer=None):
    """Check if property updates should be halted.

    Args:
        context: Blender context
        layer: Optional layer to check updating_property flag

    Returns:
        bool: True if updates should be halted
    """
    if hasattr(context.window_manager, 'mixar_ui'):
        if context.window_manager.mixar_ui.halt_prop_update:
            return True

    if layer and layer.updating_property:
        return True

    return False


def _get_active_ui_layer(context):
    """Get the active UI layer from scene.

    Returns:
        MixarLayer or None if no valid active layer
    """
    scene = context.scene
    if scene.mixar_active_layer_index < 0 or scene.mixar_active_layer_index >= len(
        scene.mixar_layers
    ):
        return None
    return scene.mixar_layers[scene.mixar_active_layer_index]


def update_channel_color_value(channel, context):
    """Update callback when channel color value changes"""
    # Check halt flag
    layer, _ = get_parent_layer_from_channel(channel, context)
    if _is_update_halted(context, layer):
        return

    if not channel.source_node_name:
        return

    ui_layer = _get_active_ui_layer(context)
    if not ui_layer:
        return

    layer_tree = _get_layer_tree(context, ui_layer)
    if not layer_tree:
        return

    # Find the source node and update it
    source_node = layer_tree.nodes.get(channel.source_node_name)
    if source_node and hasattr(source_node.outputs[0], "default_value"):
        source_node.outputs[0].default_value = channel.color_value


def update_channel_scalar_value(channel, context):
    """Update callback when channel scalar value changes"""
    # Check halt flag
    layer, _ = get_parent_layer_from_channel(channel, context)
    if _is_update_halted(context, layer):
        return

    if not channel.source_node_name:
        return

    ui_layer = _get_active_ui_layer(context)
    if not ui_layer:
        return

    layer_tree = _get_layer_tree(context, ui_layer)
    if not layer_tree:
        return

    # Find the source node and update it
    source_node = layer_tree.nodes.get(channel.source_node_name)
    if source_node and hasattr(source_node.outputs[0], "default_value"):
        source_node.outputs[0].default_value = channel.scalar_value


def update_channel_intensity(channel, context):
    """Update callback when channel intensity_value changes"""
    # Check halt flag
    layer, _ = get_parent_layer_from_channel(channel, context)
    if _is_update_halted(context, layer):
        return

    if not channel.intensity_node_name:
        return

    ui_layer = _get_active_ui_layer(context)
    if not ui_layer:
        return

    layer_tree = _get_layer_tree(context, ui_layer)
    if not layer_tree:
        return

    # Find the intensity node and update its factor (input[1])
    intensity_node = layer_tree.nodes.get(channel.intensity_node_name)
    if intensity_node and intensity_node.type == "MATH":
        intensity_node.inputs[1].default_value = channel.intensity_value


def _get_backend_layer(context, layer):
    """Get the backend YLayer for a UI layer.

    Args:
        context: Blender context
        layer: The UI layer

    Returns:
        tuple: (backend_layer, mp) or (None, None) if not found
    """
    obj = context.active_object
    if not obj or not obj.active_material:
        return (None, None)

    mat = obj.active_material
    if not mat.use_nodes:
        return (None, None)

    # Find Mixar group node
    node = None
    for n in mat.node_tree.nodes:
        if n.type == 'GROUP' and n.node_tree and hasattr(n.node_tree, 'mp'):
            node = n
            break

    if not node:
        return (None, None)

    tree = node.node_tree
    mp = tree.mp

    # Get backend layer
    if layer.mixar_layer_idx < 0 or layer.mixar_layer_idx >= len(mp.layers):
        return (None, None)

    return (mp.layers[layer.mixar_layer_idx], mp)


def update_layer_visible(layer, context):
    """Update callback when layer visibility changes"""
    if _is_update_halted(context, layer):
        return

    backend_layer, _ = _get_backend_layer(context, layer)
    if not backend_layer:
        return

    # Sync visibility to backend
    # This will trigger backend's update_layer_enable callback which handles node reconnections
    backend_layer.enable = layer.visible


def update_layer_opacity(layer, context):
    """Update callback when layer opacity changes"""
    if _is_update_halted(context, layer):
        return

    backend_layer, _ = _get_backend_layer(context, layer)
    if not backend_layer:
        return

    # Sync opacity to backend intensity_value
    backend_layer.intensity_value = layer.opacity


def update_layer_blend_mode(layer, context):
    """Update callback when layer blend mode changes"""
    if _is_update_halted(context, layer):
        return

    backend_layer, _ = _get_backend_layer(context, layer)
    if not backend_layer:
        return

    # Sync blend mode to backend
    # Note: Blend mode changes may require node reconnections, but YLayer.blend_mode
    # doesn't have an update callback. We may need to manually trigger reconnection
    # or add an update callback to YLayer.blend_mode in the future
    backend_layer.blend_mode = layer.blend_mode


def update_channel_enable(channel, context):
    """Update callback when channel enable state changes.

    When a channel is enabled/disabled on a layer, this triggers node reconnection
    to properly set up or remove connections for that channel.
    Based on Mixar Paint's update_layer_mask_channel_enable pattern.
    """
    # Import here to avoid circular imports
    from ...core.node.node_utils import get_active_mpaint_node
    from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
    from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes

    # Check halt flag
    if hasattr(context.window_manager, 'mixar_ui'):
        if context.window_manager.mixar_ui.halt_prop_update:
            return

    # Get the active mpaint node and tree
    node = get_active_mpaint_node()
    if not node or not node.node_tree:
        return

    tree = node.node_tree
    mp = tree.mp

    # Check if updates are halted
    if mp.halt_update or mp.halt_reconnect:
        return

    # Find which layer this channel belongs to by checking all layers
    # The channel object is part of a layer's channels collection
    target_layer = None
    for layer in mp.layers:
        for i, ch in enumerate(layer.channels):
            if ch == channel:
                target_layer = layer
                break
        if target_layer:
            break

    if not target_layer:
        return

    # Reconnect the layer's internal nodes first
    reconnect_layer_nodes(target_layer)
    rearrange_layer_nodes(target_layer)

    # Then reconnect the entire tree to update all connections
    reconnect_mp_nodes(tree)
    rearrange_mp_nodes(tree)


def update_channel_blend_type(channel, context):
    """Update callback when channel blend type changes"""
    # Check halt flag
    if hasattr(context.window_manager, 'mixar_ui'):
        if context.window_manager.mixar_ui.halt_prop_update:
            return

    layer, _ = get_parent_layer_from_channel(channel, context)
    if layer and layer.updating_property:
        return

    # TODO: Sync to backend YLayerChannel.blend_type
    # This may require reconnecting blend nodes
