# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI refresh system for Mixar layers
Implements Mixar Paint-style UI update mechanism with bidirectional sync
between backend (YLayer/mp) and frontend (MixarLayer) properties.
"""

import bpy
from typing import Optional


def get_active_mixar_node():
    """Get the active Mixar paint node (group node with mp tree)"""
    obj = bpy.context.active_object
    if not obj or not obj.active_material:
        return None

    mat = obj.active_material
    if not mat.use_nodes:
        return None

    # Look for Mixar group node in material
    for node in mat.node_tree.nodes:
        if node.type == 'GROUP' and node.node_tree and hasattr(node.node_tree, 'mp'):
            return node

    return None


def update_mixar_ui():
    """Main UI update function - detects state changes and triggers refresh.

    This is the gatekeeper function called at the start of every panel draw.
    It checks if the context has changed (material switched, layer selection changed)
    or if a manual refresh was requested, then rebuilds the UI collections.

    Pattern from Mixar Paint's update_mp_ui() function.

    For Properties panels: Uses WindowManager.mixar_ui.ui_layers instead of Scene.mixar_layers
    because Scene properties are read-only during Properties panel draw.
    """
    context = bpy.context
    wm = context.window_manager

    # Check if UI state exists
    if not hasattr(wm, 'mixar_ui'):
        return

    mixar_ui = wm.mixar_ui

    # Get active Mixar node
    node = get_active_mixar_node()
    if not node or node.type != 'GROUP' or not node.node_tree:
        # No valid node - clear UI
        if len(mixar_ui.ui_layers) > 0:
            mixar_ui.ui_layers.clear()
            mixar_ui.active_tree_name = ""
        return

    tree = node.node_tree
    mp = tree.mp

    # Check if layer count consistency is maintained
    if len(mp.layers) > 0:
        if len(mixar_ui.ui_layers) != len(mp.layers):
            mixar_ui.needs_ui_refresh = True

    # Detect state changes that require UI rebuild
    layer_changed = (
        mixar_ui.active_tree_name != tree.name or
        mixar_ui.active_layer_index != mp.active_layer_index
    )
    state_changed = layer_changed or mixar_ui.needs_ui_refresh

    if state_changed:
        # Store new state
        mixar_ui.active_tree_name = tree.name
        mixar_ui.active_layer_index = mp.active_layer_index

        # Only reset mask selection when layer actually changes, not on general refresh
        if layer_changed:
            mixar_ui.editing_mask_index = -1

        mixar_ui.needs_ui_refresh = False

        # PREVENT CIRCULAR UPDATES - Critical pattern!
        mixar_ui.halt_prop_update = True

        try:
            # Rebuild UI from backend
            simple_update_mixar_tree_ui(context, node, tree, mp)

            # BACKWARD COMPATIBILITY: Sync to old mpui.layer_ui system
            # This prevents crashes in code that still uses layer_ui.channels/masks
            update_mp_ui_layer_collections(context, node, tree, mp)
        finally:
            # RE-ENABLE PROPERTY UPDATES
            mixar_ui.halt_prop_update = False


def simple_update_mixar_tree_ui(context=None, node=None, tree=None, mp=None):
    """Full UI rebuild - sync all backend data to frontend UI properties.

    Clears and rebuilds WindowManager.mixar_ui.ui_layers from mp.layers data.
    This is the main synchronization point from backend → frontend.

    Uses WindowManager instead of Scene for Properties panel compatibility
    (Scene is read-only during Properties panel draw).

    Args:
        context: Blender context (optional, will use bpy.context if not provided)
        node: Mixar group node (optional, will find if not provided)
        tree: Node tree (optional, will get from node if not provided)
        mp: MPaint root property (optional, will get from tree if not provided)
    """
    if context is None:
        context = bpy.context

    wm = context.window_manager

    # Check if mixar_ui exists
    if not hasattr(wm, 'mixar_ui'):
        return

    mixar_ui = wm.mixar_ui

    # Get node/tree/mp if not provided
    if node is None:
        node = get_active_mixar_node()
        if not node:
            mixar_ui.ui_layers.clear()
            return

    if tree is None:
        tree = node.node_tree
        if not tree:
            mixar_ui.ui_layers.clear()
            return

    if mp is None:
        mp = tree.mp

    # Preserve selections before clearing
    preserved_selections = {}
    for i, ui_layer in enumerate(mixar_ui.ui_layers):
        if ui_layer.selected:
            # Store by name since indices may change
            preserved_selections[ui_layer.name] = True

    # Clear existing UI layers
    mixar_ui.ui_layers.clear()

    # Rebuild UI layers from backend
    for layer_idx, mp_layer in enumerate(mp.layers):
        ui_layer = mixar_ui.ui_layers.add()

        # Sync basic properties
        ui_layer.name = mp_layer.name
        ui_layer.layer_type = mp_layer.type
        ui_layer.visible = mp_layer.enable

        # Restore selection state
        if mp_layer.name in preserved_selections:
            ui_layer.selected = True

        # Opacity - check both alpha and intensity_value for compatibility
        if hasattr(mp_layer, 'alpha'):
            ui_layer.opacity = mp_layer.alpha
        elif hasattr(mp_layer, 'intensity_value'):
            ui_layer.opacity = mp_layer.intensity_value
        else:
            ui_layer.opacity = 1.0

        # Blend mode - get from first enabled channel (Mixar Paint pattern)
        # Layers don't have blend_mode, channels do
        blend_mode = 'MIX'  # default
        if len(mp_layer.channels) > 0:
            # Find first enabled channel
            for ch in mp_layer.channels:
                if ch.enable:
                    blend_mode = ch.blend_type if hasattr(ch, 'blend_type') else 'MIX'
                    break
        ui_layer.blend_mode = blend_mode

        # Store backend reference
        ui_layer.mixar_layer_idx = layer_idx

    # Update active layer index
    mixar_ui.active_layer_index = mp.active_layer_index

    # Also sync to scene.mixar_layers if we're in a writable context (for operators)
    try:
        scene = context.scene
        if scene:
            scene.mixar_active_layer_index = mp.active_layer_index
    except (AttributeError, RuntimeError):
        # Scene not writable - skip
        pass


def reconnect_mixar_tree_ui():
    """Lightweight UI refresh - update node references and states only.

    This is faster than full rebuild - only updates essential properties
    like enable states, intensity values, and node name references.
    Use this after node reconnections or minor backend changes.
    """
    context = bpy.context
    scene = context.scene

    node = get_active_mixar_node()
    if not node or not node.node_tree:
        return

    tree = node.node_tree
    mp = tree.mp

    # Check length consistency
    if len(scene.mixar_layers) != len(mp.layers):
        # Need full refresh
        simple_update_mixar_tree_ui(context, node, tree, mp)
        return

    # Update existing UI layers with fresh data
    for layer_idx, mp_layer in enumerate(mp.layers):
        if layer_idx >= len(scene.mixar_layers):
            break

        ui_layer = scene.mixar_layers[layer_idx]

        # Update key properties
        ui_layer.name = mp_layer.name
        ui_layer.visible = mp_layer.enable
        ui_layer.opacity = mp_layer.alpha

        # Update node references (they may have been recreated)
        ui_layer.mixar_layer_idx = layer_idx
        ui_layer.mixar_group_node = node.name

        # Update channel states
        reconnect_channels_ui(ui_layer, mp_layer, tree)

        # Update mask states
        reconnect_masks_ui(ui_layer, mp_layer, tree)

    # Update active index
    scene.mixar_active_layer_index = mp.active_layer_index


def sync_channels_from_backend(ui_layer, mp_layer, tree):
    """Sync all channels from backend to UI layer.

    Args:
        ui_layer: MixarLayer UI property
        mp_layer: YLayer backend property
        tree: Node tree containing the layer
    """
    # Clear existing channels
    ui_layer.channels.clear()

    # Get root channels from mp
    mp = tree.mp

    for ch_idx, mp_channel in enumerate(mp.channels):
        # Check if this channel is enabled for this layer
        if ch_idx >= len(mp_layer.channels):
            continue

        mp_layer_ch = mp_layer.channels[ch_idx]

        ui_channel = ui_layer.channels.add()
        ui_channel.name = mp_channel.name
        ui_channel.enable = mp_layer_ch.enable

        # Sync blend settings
        if hasattr(mp_layer_ch, 'blend_type'):
            ui_channel.blend_type = mp_layer_ch.blend_type

        # Sync intensity
        if hasattr(mp_layer_ch, 'intensity_value'):
            ui_channel.intensity_value = mp_layer_ch.intensity_value

        # Sync values for Fill layers
        if mp_layer.type == 'IMAGE' and hasattr(mp_layer_ch, 'default_value'):
            # Color channel
            if mp_channel.type in {'RGB', 'RGBA'}:
                if hasattr(mp_layer_ch, 'default_value') and len(mp_layer_ch.default_value) >= 3:
                    ui_channel.color_value = mp_layer_ch.default_value[:3]
            # Scalar channel
            else:
                if hasattr(mp_layer_ch, 'default_value'):
                    ui_channel.scalar_value = mp_layer_ch.default_value

        # Store node references
        if hasattr(mp_layer_ch, 'source'):
            ui_channel.source_node_name = mp_layer_ch.source
        if hasattr(mp_layer_ch, 'blend'):
            ui_channel.blend_node_name = mp_layer_ch.blend
        if hasattr(mp_layer_ch, 'intensity'):
            ui_channel.intensity_node_name = mp_layer_ch.intensity


def sync_masks_from_backend(ui_layer, mp_layer, tree):
    """Sync all masks from backend to UI layer.

    Args:
        ui_layer: MixarLayer UI property
        mp_layer: YLayer backend property
        tree: Node tree containing the layer
    """
    # Clear existing masks
    ui_layer.masks.clear()

    for mask_idx, mp_mask in enumerate(mp_layer.masks):
        ui_mask = ui_layer.masks.add()

        ui_mask.name = mp_mask.name if hasattr(mp_mask, 'name') else f"Mask {mask_idx}"
        ui_mask.enable = mp_mask.enable if hasattr(mp_mask, 'enable') else True
        ui_mask.type = mp_mask.type if hasattr(mp_mask, 'type') else 'IMAGE'

        # Sync intensity
        if hasattr(mp_mask, 'intensity_value'):
            ui_mask.intensity_value = mp_mask.intensity_value


def reconnect_channels_ui(ui_layer, mp_layer, tree):
    """Lightweight channel sync - only update essential properties.

    Args:
        ui_layer: MixarLayer UI property
        mp_layer: YLayer backend property
        tree: Node tree containing the layer
    """
    mp = tree.mp

    # Check length consistency
    if len(ui_layer.channels) != len(mp.channels):
        # Need full sync
        sync_channels_from_backend(ui_layer, mp_layer, tree)
        return

    for ch_idx, ui_channel in enumerate(ui_layer.channels):
        if ch_idx >= len(mp_layer.channels):
            continue

        mp_layer_ch = mp_layer.channels[ch_idx]

        # Update enable and intensity
        ui_channel.enable = mp_layer_ch.enable
        if hasattr(mp_layer_ch, 'intensity_value'):
            ui_channel.intensity_value = mp_layer_ch.intensity_value


def reconnect_masks_ui(ui_layer, mp_layer, tree):
    """Lightweight mask sync - only update essential properties.

    Args:
        ui_layer: MixarLayer UI property
        mp_layer: YLayer backend property
        tree: Node tree containing the layer
    """
    # Check length consistency
    if len(ui_layer.masks) != len(mp_layer.masks):
        # Need full sync
        sync_masks_from_backend(ui_layer, mp_layer, tree)
        return

    for mask_idx, ui_mask in enumerate(ui_layer.masks):
        if mask_idx >= len(mp_layer.masks):
            continue

        mp_mask = mp_layer.masks[mask_idx]

        # Update enable and intensity
        ui_mask.enable = mp_mask.enable if hasattr(mp_mask, 'enable') else True
        if hasattr(mp_mask, 'intensity_value'):
            ui_mask.intensity_value = mp_mask.intensity_value


def request_ui_refresh():
    """Request a UI refresh on next draw cycle.

    Call this after backend operations that modify mp data:
    - Layer creation/deletion/reordering
    - Node reconnections
    - Channel/mask modifications
    """
    context = bpy.context
    if hasattr(context.window_manager, 'mixar_ui'):
        context.window_manager.mixar_ui.needs_ui_refresh = True


def update_mp_ui_layer_collections(context=None, node=None, tree=None, mp=None):
    """Sync backend layer data to mpui.layer_ui for backward compatibility.

    This maintains the old Mixar Paint UI update pattern while the new UI uses mixar_ui.
    The old system stores per-layer UI expansion states in mpui.layer_ui.channels
    and mpui.layer_ui.masks collections, which must be populated to prevent crashes
    in code that still references them.

    Args:
        context: Blender context (optional, will use bpy.context if not provided)
        node: Mixar group node (optional, will find if not provided)
        tree: Node tree (optional, will get from node if not provided)
        mp: MPaint root property (optional, will get from tree if not provided)
    """
    if context is None:
        context = bpy.context

    wm = context.window_manager

    # Check if old UI system exists
    if not hasattr(wm, 'mpui'):
        return

    mpui = wm.mpui

    # Check if layer_ui exists
    if not hasattr(mpui, 'layer_ui'):
        return

    # Get active layer
    if len(mp.layers) == 0:
        # No layers - clear collections
        if hasattr(mpui.layer_ui, 'channels'):
            mpui.layer_ui.channels.clear()
        if hasattr(mpui.layer_ui, 'masks'):
            mpui.layer_ui.masks.clear()
        return

    layer = mp.layers[mp.active_layer_index]

    # NOTE: Expansion states (expand_channels, expand_masks, expand_source) are now
    # stored globally in mixar_ui (WindowManager) instead of per-layer, so they persist
    # across layer switches and UI refreshes. No need to sync them here anymore.
    # Legacy expand_content and expand_vector still sync if they exist on layers
    if hasattr(layer, 'expand_content'):
        mpui.layer_ui.expand_content = layer.expand_content
    if hasattr(layer, 'expand_vector'):
        mpui.layer_ui.expand_vector = layer.expand_vector

    # Rebuild channel UI collection to match backend
    if hasattr(mpui.layer_ui, 'channels'):
        mpui.layer_ui.channels.clear()
        for i, ch in enumerate(layer.channels):
            c = mpui.layer_ui.channels.add()

            # Copy critical UI expansion states
            if hasattr(ch, 'expand_content'):
                c.expand_content = ch.expand_content
            if hasattr(ch, 'expand_source'):
                c.expand_source = ch.expand_source
            if hasattr(ch, 'expand_bump_settings'):
                c.expand_bump_settings = ch.expand_bump_settings
            if hasattr(ch, 'expand_intensity_settings'):
                c.expand_intensity_settings = ch.expand_intensity_settings
            if hasattr(ch, 'expand_base_vector'):
                c.expand_base_vector = ch.expand_base_vector

            # Copy additional expansion states if they exist
            for attr in ['expand_transition_bump_settings', 'expand_transition_ramp_settings',
                        'expand_transition_ao_settings', 'expand_subdiv_settings',
                        'expand_parallax_settings', 'expand_alpha_settings',
                        'expand_bake_to_vcol_settings', 'expand_input_bump_settings',
                        'expand_smooth_bump_settings', 'expand_input_settings',
                        'expand_blend_settings', 'expand_source_1', 'expand_baked_data']:
                if hasattr(ch, attr) and hasattr(c, attr):
                    setattr(c, attr, getattr(ch, attr))

    # Rebuild mask UI collection to match backend
    if hasattr(mpui.layer_ui, 'masks'):
        mpui.layer_ui.masks.clear()
        for i, mask in enumerate(layer.masks):
            m = mpui.layer_ui.masks.add()

            # Copy critical UI expansion states
            if hasattr(mask, 'expand_content'):
                m.expand_content = mask.expand_content
            if hasattr(mask, 'expand_channels'):
                m.expand_channels = mask.expand_channels
            if hasattr(mask, 'expand_source'):
                m.expand_source = mask.expand_source
            if hasattr(mask, 'expand_vector'):
                m.expand_vector = mask.expand_vector
