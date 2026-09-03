# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update callback functions for modifier properties.

This module contains all update callback functions that are triggered when
modifier properties change. These handle updating shader nodes and
reconnecting layer/channel nodes as needed.
"""

import re

from ..io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ..io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ..modifier.modifier_channel import get_modifier_channel_type
from ..modifier.modifier_commons import check_modifier_nodes
from ..subtree.get_subtree import get_mod_tree


def update_modifier_enable(self, context):
    """Update callback for when a modifier's enable state changes.

    This function is triggered when a modifier is enabled or disabled. It updates
    the modifier's shader nodes and reconnects/rearranges the layer or channel
    node structure as needed.

    Args:
        self: The modifier property group instance.
        context: The Blender context containing scene and UI state.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    tree = get_mod_tree(self)

    check_modifier_nodes(self, tree)

    match1 = re.match(
        r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers\[(\d+)\]",
        self.path_from_id(),
    )
    match2 = re.match(r"mp\.layers\[(\d+)\]\.modifiers\[(\d+)\]", self.path_from_id())
    match3 = re.match(r"mp\.channels\[(\d+)\]\.modifiers\[(\d+)\]", self.path_from_id())

    if match1 or match2:
        if match1:
            layer = mp.layers[int(match1.group(1))]
        else:
            layer = mp.layers[int(match2.group(1))]

        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

    elif match3:
        channel = mp.channels[int(match3.group(1))]
        reconnect_mp_nodes(self.id_data)
        rearrange_mp_nodes(self.id_data)


def update_modifier_shortcut(self, context):
    """Update callback for when a modifier's shortcut property changes.

    Ensures only one modifier or the layer's color shortcut can be active at a time.
    When a modifier's shortcut is enabled, all other shortcuts in the same layer
    or channel are disabled.

    Args:
        self: The modifier property group instance.
        context: The Blender context containing scene and UI state.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    mod = self

    if mod.shortcut:

        match1 = re.match(
            r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers\[(\d+)\]",
            mod.path_from_id(),
        )
        match2 = re.match(
            r"mp\.layers\[(\d+)\]\.modifiers\[(\d+)\]", mod.path_from_id()
        )
        match3 = re.match(
            r"mp\.channels\[(\d+)\]\.modifiers\[(\d+)\]", mod.path_from_id()
        )

        if match1 or match2:

            layer = mp.layers[int(match1.group(1))]
            layer.color_shortcut = False

            for m in layer.modifiers:
                if m != mod:
                    m.shortcut = False

            for ch in layer.channels:
                for m in ch.modifiers:
                    if m != mod:
                        m.shortcut = False

        elif match3:
            channel = mp.channels[int(match2.group(1))]
            for m in channel.modifiers:
                if m != mod:
                    m.shortcut = False


def update_use_clamp(self, context):
    """Update callback for when a modifier's use_clamp property changes.

    Updates the shader nodes to enable or disable clamping of values to the 0-1 range.
    Applies to MULTIPLIER and MATH modifier types.

    Args:
        self: The modifier property group instance.
        context: The Blender context containing scene and UI state.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return
    tree = get_mod_tree(self)
    channel_type = get_modifier_channel_type(self)

    if self.type == "MULTIPLIER":
        multiplier = tree.nodes.get(self.multiplier)
        multiplier.inputs[2].default_value = (
            1.0 if self.use_clamp and self.enable else 0.0
        )
    elif self.type == "MATH":
        math = tree.nodes.get(self.math)
        math.node_tree.nodes.get("Math.R").use_clamp = self.use_clamp
        math.node_tree.nodes.get("Math.A").use_clamp = self.use_clamp
        if channel_type != "VALUE":
            math.node_tree.nodes.get("Math.G").use_clamp = self.use_clamp
            math.node_tree.nodes.get("Math.B").use_clamp = self.use_clamp


def update_affect_color(self, context):
    """Update callback for when a modifier's affect_color property changes.

    Updates the modifier to enable or disable its effect on the color (RGB) channels.
    Currently only affects COLOR_RAMP modifiers.

    Args:
        self: The modifier property group instance.
        context: The Blender context containing scene and UI state.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return
    tree = get_mod_tree(self)

    if self.type == "COLOR_RAMP":
        update_modifier_enable(self, context)


def update_affect_alpha(self, context):
    """Update callback for when a modifier's affect_alpha property changes.

    Updates the modifier to enable or disable its effect on the alpha channel.
    Applies to MATH and COLOR_RAMP modifier types.

    Args:
        self: The modifier property group instance.
        context: The Blender context containing scene and UI state.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return
    tree = get_mod_tree(self)

    if self.type == "MATH":
        math = tree.nodes.get(self.math).node_tree
        alpha = math.nodes.get("Mix.A")
        if self.affect_alpha:
            alpha.mute = False
        else:
            alpha.mute = True

    elif self.type == "COLOR_RAMP":
        update_modifier_enable(self, context)


def update_math_method(self, context):
    """Update callback for when a MATH modifier's operation method changes.

    Updates all math nodes in the shader tree to use the new mathematical operation
    (e.g., ADD, MULTIPLY, POWER, etc.).

    Args:
        self: The modifier property group instance.
        context: The Blender context containing scene and UI state.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return
    tree = get_mod_tree(self)
    channel_type = get_modifier_channel_type(self)

    if self.type == "MATH":
        math = tree.nodes.get(self.math)
        math.node_tree.nodes.get("Math.R").operation = self.math_meth
        math.node_tree.nodes.get("Math.A").operation = self.math_meth
        if channel_type != "VALUE":
            math.node_tree.nodes.get("Math.G").operation = self.math_meth
            math.node_tree.nodes.get("Math.B").operation = self.math_meth


def update_multiplier_val_input(self, context):
    """Update callback for when a MULTIPLIER modifier's value inputs change.

    Updates the shader node inputs with new multiplier values for R, G, B, and Alpha
    channels when the modifier is enabled.

    Args:
        self: The modifier property group instance.
        context: The Blender context containing scene and UI state.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return
    channel_type = get_modifier_channel_type(self)
    tree = get_mod_tree(self)

    if self.type == "MULTIPLIER":
        multiplier = tree.nodes.get(self.multiplier)
        multiplier.inputs[3].default_value = (
            self.multiplier_r_val if self.enable else 1.0
        )
        if channel_type == "VALUE":
            multiplier.inputs[4].default_value = (
                self.multiplier_a_val if self.enable else 1.0
            )
        else:
            multiplier.inputs[4].default_value = (
                self.multiplier_g_val if self.enable else 1.0
            )
            multiplier.inputs[5].default_value = (
                self.multiplier_b_val if self.enable else 1.0
            )
            multiplier.inputs[6].default_value = (
                self.multiplier_a_val if self.enable else 1.0
            )


def update_oc_col(self, context):
    """Update callback for when an OVERRIDE_COLOR modifier's color value changes.

    Updates the shader node with the new override color or value. Handles both
    RGB color channels and single VALUE channels.

    Args:
        self: The modifier property group instance.
        context: The Blender context containing scene and UI state.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return
    channel_type = get_modifier_channel_type(self)
    tree = get_mod_tree(self)

    if self.type == "OVERRIDE_COLOR":  # and not self.oc_use_normal_base:
        oc = tree.nodes.get(self.oc)

        if channel_type == "VALUE":
            col = (self.oc_val, self.oc_val, self.oc_val, 1.0)
        else:
            col = self.oc_col

        if oc:
            oc.inputs["Override Color"].default_value = col


def update_invert_channel(self, context):
    """Update callback for when an INVERT modifier's channel enable states change.

    Updates the shader node inputs to enable or disable inversion for specific
    channels (R, G, B, and/or Alpha) based on the modifier's settings.

    Args:
        self: The modifier property group instance.
        context: The Blender context containing scene and UI state.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return
    channel_type = get_modifier_channel_type(self)
    tree = get_mod_tree(self)
    invert = tree.nodes.get(self.invert)

    invert.inputs[2].default_value = (
        1.0 if self.invert_r_enable and self.enable else 0.0
    )
    if channel_type == "VALUE":
        invert.inputs[3].default_value = (
            1.0 if self.invert_a_enable and self.enable else 0.0
        )
    else:
        invert.inputs[3].default_value = (
            1.0 if self.invert_g_enable and self.enable else 0.0
        )
        invert.inputs[4].default_value = (
            1.0 if self.invert_b_enable and self.enable else 0.0
        )
        invert.inputs[5].default_value = (
            1.0 if self.invert_a_enable and self.enable else 0.0
        )
