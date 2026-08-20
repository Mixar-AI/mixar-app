# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update callbacks for UI property groups.

This module contains all the update callback functions that synchronize
UI expansion states from UI property groups to backend data structures.
"""

import re

from ...core.node.node_utils import get_active_mpaint_node
from ...utils.common import get_active_layer_safe


def update_layer_ui(self, context):
    """Update callback when layer UI properties change.

    Synchronizes UI expansion states from the UI property group to the backend layer.

    Args:
        self: The layer UI property instance.
        context: The Blender context.

    Returns:
        None
    """
    if not hasattr(context.window_manager, 'mpui'):
        return
    # Check both halt flags - mpui (old system) and mixar_ui (new system)
    mpui = context.window_manager.mpui
    if mpui.halt_prop_update:
        return
    if hasattr(context.window_manager, 'mixar_ui'):
        if context.window_manager.mixar_ui.halt_prop_update:
            return

    group_node = get_active_mpaint_node()
    if not group_node:
        return
    mp = group_node.node_tree.mp

    layer = get_active_layer_safe(mp)
    if not layer:
        return

    layer.expand_content = self.expand_content
    layer.expand_vector = self.expand_vector
    layer.expand_masks = self.expand_masks
    layer.expand_source = self.expand_source
    layer.expand_channels = self.expand_channels


def update_channel_ui(self, context):
    """Update callback when channel UI properties change.

    Synchronizes UI expansion states from the UI property group to the backend channel.
    Handles both layer channels and root channels based on the property path.

    Args:
        self: The channel UI property instance.
        context: The Blender context.

    Returns:
        None
    """
    # Check both halt flags - mpui (old system) and mixar_ui (new system)
    mpui = context.window_manager.mpui
    if mpui.halt_prop_update:
        return
    if hasattr(context.window_manager, 'mixar_ui'):
        if context.window_manager.mixar_ui.halt_prop_update:
            return

    group_node = get_active_mpaint_node()
    if not group_node:
        return
    mp = group_node.node_tree.mp
    if len(mp.channels) == 0:
        return

    match1 = re.match(r"mpui\.layer_ui\.channels\[(\d+)\]", self.path_from_id())
    match2 = re.match(r"mpui\.channel_ui", self.path_from_id())

    ch = None
    if match1:
        layer = get_active_layer_safe(mp)
        if layer:
            ch_idx = int(match1.group(1))
            if 0 <= ch_idx < len(layer.channels):
                ch = layer.channels[ch_idx]
    elif match2:
        if 0 <= mp.active_channel_index < len(mp.channels):
            ch = mp.channels[mp.active_channel_index]

    if not ch:
        return

    ch.expand_content = self.expand_content
    if hasattr(ch, "expand_bump_settings"):
        ch.expand_bump_settings = self.expand_bump_settings
    if hasattr(ch, "expand_base_vector"):
        ch.expand_base_vector = self.expand_base_vector
    if hasattr(ch, "expand_subdiv_settings"):
        ch.expand_subdiv_settings = self.expand_subdiv_settings
    if hasattr(ch, "expand_parallax_settings"):
        ch.expand_parallax_settings = self.expand_parallax_settings
    if hasattr(ch, "expand_alpha_settings"):
        ch.expand_alpha_settings = self.expand_alpha_settings
    if hasattr(ch, "expand_bake_to_vcol_settings"):
        ch.expand_bake_to_vcol_settings = self.expand_bake_to_vcol_settings
    if hasattr(ch, "expand_input_bump_settings"):
        ch.expand_input_bump_settings = self.expand_input_bump_settings
    if hasattr(ch, "expand_smooth_bump_settings"):
        ch.expand_smooth_bump_settings = self.expand_smooth_bump_settings
    if hasattr(ch, "expand_intensity_settings"):
        ch.expand_intensity_settings = self.expand_intensity_settings
    if hasattr(ch, "expand_transition_bump_settings"):
        ch.expand_transition_bump_settings = self.expand_transition_bump_settings
    if hasattr(ch, "expand_transition_ramp_settings"):
        ch.expand_transition_ramp_settings = self.expand_transition_ramp_settings
    if hasattr(ch, "expand_transition_ao_settings"):
        ch.expand_transition_ao_settings = self.expand_transition_ao_settings
    if hasattr(ch, "expand_input_settings"):
        ch.expand_input_settings = self.expand_input_settings
    if hasattr(ch, "expand_blend_settings"):
        ch.expand_blend_settings = self.expand_blend_settings
    if hasattr(ch, "expand_source"):
        ch.expand_source = self.expand_source
    if hasattr(ch, "expand_source_1"):
        ch.expand_source_1 = self.expand_source_1


def update_modifier_ui(self, context):
    """Update callback when modifier UI properties change.

    Synchronizes UI expansion states from the UI property group to the backend modifier.
    Uses regex matching to determine which modifier is being updated based on the property path.

    Args:
        self: The modifier UI property instance.
        context: The Blender context.

    Returns:
        None
    """
    # Check both halt flags - mpui (old system) and mixar_ui (new system)
    mpui = context.window_manager.mpui
    if mpui.halt_prop_update:
        return
    if hasattr(context.window_manager, 'mixar_ui'):
        if context.window_manager.mixar_ui.halt_prop_update:
            return

    group_node = get_active_mpaint_node()
    if not group_node:
        return
    mp = group_node.node_tree.mp

    match1 = re.match(
        r"mpui\.layer_ui\.channels\[(\d+)\]\.modifiers\[(\d+)\]", self.path_from_id()
    )
    match2 = re.match(
        r"mpui\.layer_ui\.channels\[(\d+)\]\.modifiers_1\[(\d+)\]", self.path_from_id()
    )
    match3 = re.match(r"mpui\.channel_ui\.modifiers\[(\d+)\]", self.path_from_id())
    match4 = re.match(r"mpui\.layer_ui\.modifiers\[(\d+)\]", self.path_from_id())
    match5 = re.match(
        r"mpui\.layer_ui\.masks\[(\d+)\]\.modifiers\[(\d+)\]", self.path_from_id()
    )
    if match1:
        mod = (
            mp.layers[mp.active_layer_index]
            .channels[int(match1.group(1))]
            .modifiers[int(match1.group(2))]
        )
    elif match2:
        mod = (
            mp.layers[mp.active_layer_index]
            .channels[int(match2.group(1))]
            .modifiers_1[int(match2.group(2))]
        )
    elif match3:
        mod = mp.channels[mp.active_channel_index].modifiers[int(match3.group(1))]
    elif match4:
        mod = mp.layers[mp.active_layer_index].modifiers[int(match4.group(1))]
    elif match5:
        mod = (
            mp.layers[mp.active_layer_index]
            .masks[int(match5.group(1))]
            .modifiers[int(match5.group(2))]
        )
    # else: return #yolo

    mod.expand_content = self.expand_content


def update_noncontextual_channel_ui(self, context):
    """Update callback for non-contextual channel UI properties.

    Handles UI updates for channel properties that don't depend on the active layer context,
    such as baked data expansion state.

    Args:
        self: The channel UI property instance.
        context: The Blender context.

    Returns:
        None
    """
    group_node = get_active_mpaint_node()
    if not group_node:
        return
    mp = group_node.node_tree.mp
    if len(mp.channels) == 0:
        return

    m = re.match(r"mpui\.channels\[(\d+)\]", self.path_from_id())

    if m:
        ch = mp.channels[int(m.group(1))]
    else:
        return

    if hasattr(ch, "expand_baked_data"):
        ch.expand_baked_data = self.expand_baked_data


def update_mask_ui(self, context):
    """Update callback when mask UI properties change.

    Synchronizes UI expansion states from the UI property group to the backend mask.

    Args:
        self: The mask UI property instance.
        context: The Blender context.

    Returns:
        None
    """
    # Check both halt flags - mpui (old system) and mixar_ui (new system)
    mpui = context.window_manager.mpui
    if mpui.halt_prop_update:
        return
    if hasattr(context.window_manager, 'mixar_ui'):
        if context.window_manager.mixar_ui.halt_prop_update:
            return

    group_node = get_active_mpaint_node()
    if not group_node:
        return
    mp = group_node.node_tree.mp
    # if len(mp.channels) == 0: return

    match = re.match(r"mpui\.layer_ui\.masks\[(\d+)\]", self.path_from_id())
    mask = mp.layers[mp.active_layer_index].masks[int(match.group(1))]

    mask.expand_content = self.expand_content
    mask.expand_channels = self.expand_channels
    mask.expand_source = self.expand_source
    mask.expand_vector = self.expand_vector


def update_bake_target_ui(self, context):
    """Update callback when bake target UI properties change.

    Synchronizes UI expansion states from the UI property group to the backend bake target.

    Args:
        self: The bake target UI property instance.
        context: The Blender context.

    Returns:
        None
    """
    group_node = get_active_mpaint_node()
    if not group_node:
        return
    mp = group_node.node_tree.mp

    try:
        bt = mp.bake_targets[mp.active_bake_target_index]
    except:
        return

    bt.expand_content = self.expand_content
    bt.expand_r = self.expand_r
    bt.expand_g = self.expand_g
    bt.expand_b = self.expand_b
    bt.expand_a = self.expand_a


def update_mask_channel_ui(self, context):
    """Update callback when mask channel UI properties change.

    Synchronizes UI expansion states from the UI property group to the backend mask channel.

    Args:
        self: The mask channel UI property instance.
        context: The Blender context.

    Returns:
        None
    """
    # Check both halt flags - mpui (old system) and mixar_ui (new system)
    mpui = context.window_manager.mpui
    if mpui.halt_prop_update:
        return
    if hasattr(context.window_manager, 'mixar_ui'):
        if context.window_manager.mixar_ui.halt_prop_update:
            return

    group_node = get_active_mpaint_node()
    if not group_node:
        return
    mp = group_node.node_tree.mp
    # if len(mp.channels) == 0: return

    match = re.match(
        r"mpui\.layer_ui\.masks\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id()
    )
    mask = mp.layers[mp.active_layer_index].masks[int(match.group(1))]
    mask_ch = mask.channels[int(match.group(2))]

    mask_ch.expand_content = self.expand_content
