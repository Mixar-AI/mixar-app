# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ...core.element.update_fcurves import shift_normal_modifier_fcurves_down
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes
from ...core.modifier.modifier_commons import check_modifier_nodes
from ...core.subtree.get_subtree import get_tree
from ...utils.blender_commons import get_unique_name
from .normal_map_modifier_utils import normalmap_modifier_type_items


def update_invert_channel(self, context):
    """Updates invert channel settings for RGBA channels in the modifier.

    Applies invert enable states to the corresponding invert node inputs based on
    per-channel enable flags. Updates are skipped if updates are halted or the
    modifier is disabled.

    Args:
        self: The modifier property group instance.
        context: Blender context object.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return

    match = re.match(
        r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers_1\[(\d+)\]",
        self.path_from_id(),
    )
    layer = mp.layers[int(match.group(1))]
    tree = get_tree(layer)

    invert = tree.nodes.get(self.invert)

    invert.inputs[2].default_value = (
        1.0 if self.invert_r_enable and self.enable else 0.0
    )
    invert.inputs[3].default_value = (
        1.0 if self.invert_g_enable and self.enable else 0.0
    )
    invert.inputs[4].default_value = (
        1.0 if self.invert_b_enable and self.enable else 0.0
    )
    invert.inputs[5].default_value = (
        1.0 if self.invert_a_enable and self.enable else 0.0
    )


def update_math_val_input(self, context):
    """Updates math operation input values for RGBA channels.

    Sets the default values for math node inputs based on per-channel math value
    properties. Only applies when the modifier type is 'MATH' and updates are not
    halted or the modifier is enabled.

    Args:
        self: The modifier property group instance.
        context: Blender context object.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return

    match = re.match(
        r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers_1\[(\d+)\]",
        self.path_from_id(),
    )
    layer = mp.layers[int(match.group(1))]
    tree = get_tree(layer)

    if self.type == "MATH":
        math = tree.nodes.get(self.math)
        math.inputs[2].default_value = self.math_r_val if self.enable else 0.0
        math.inputs[3].default_value = self.math_g_val if self.enable else 0.0
        math.inputs[4].default_value = self.math_b_val if self.enable else 0.0
        math.inputs[5].default_value = self.math_a_val if self.enable else 0.0


def update_math_method(self, context):
    """Updates the math operation method for all RGBA channel math nodes.

    Sets the operation type (e.g., MULTIPLY, ADD, SUBTRACT) for all four channel
    math nodes based on the modifier's math_meth property. Only applies when the
    modifier type is 'MATH'.

    Args:
        self: The modifier property group instance.
        context: Blender context object.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return

    match = re.match(
        r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers_1\[(\d+)\]",
        self.path_from_id(),
    )
    layer = mp.layers[int(match.group(1))]
    tree = get_tree(layer)

    if self.type == "MATH":
        math = tree.nodes.get(self.math)
        math.node_tree.nodes.get("Math.R").operation = self.math_meth
        math.node_tree.nodes.get("Math.G").operation = self.math_meth
        math.node_tree.nodes.get("Math.B").operation = self.math_meth
        math.node_tree.nodes.get("Math.A").operation = self.math_meth


def update_use_clamp(self, context):
    """Updates the clamp setting for all RGBA channel math nodes.

    Enables or disables value clamping for all four channel math nodes based on
    the modifier's use_clamp property. Updates are skipped if updates are halted
    or the modifier is disabled.

    Args:
        self: The modifier property group instance.
        context: Blender context object.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return

    match = re.match(
        r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers_1\[(\d+)\]",
        self.path_from_id(),
    )
    layer = mp.layers[int(match.group(1))]
    tree = get_tree(layer)

    math = tree.nodes.get(self.math)
    math.node_tree.nodes.get("Math.R").use_clamp = self.use_clamp
    math.node_tree.nodes.get("Math.A").use_clamp = self.use_clamp
    math.node_tree.nodes.get("Math.G").use_clamp = self.use_clamp
    math.node_tree.nodes.get("Math.B").use_clamp = self.use_clamp


def update_affect_alpha(self, context):
    """Updates whether the math operation affects the alpha channel.

    Mutes or unmutes the alpha mix node based on the affect_alpha property.
    Only applies when the modifier type is 'MATH'. Updates are skipped if
    updates are halted or the modifier is disabled.

    Args:
        self: The modifier property group instance.
        context: Blender context object.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return

    match = re.match(
        r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers_1\[(\d+)\]",
        self.path_from_id(),
    )
    layer = mp.layers[int(match.group(1))]
    tree = get_tree(layer)

    if self.type == "MATH":
        math = tree.nodes.get(self.math).node_tree
        alpha = math.nodes.get("Mix.A")
        if self.affect_alpha:
            alpha.mute = False
        else:
            alpha.mute = True


def update_normalmap_modifier_enable(self, context):
    """Updates the enabled state of a normal map modifier.

    Checks and updates modifier nodes, then rearranges and reconnects layer nodes
    to reflect the enabled/disabled state. Updates are skipped if the MP system
    has halted updates.

    Args:
        self: The modifier property group instance.
        context: Blender context object.

    Returns:
        None
    """

    mp = self.id_data.mp
    if mp.halt_update:
        return

    match = re.match(
        r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers_1\[(\d+)\]",
        self.path_from_id(),
    )
    layer = mp.layers[int(match.group(1))]
    tree = get_tree(layer)

    check_modifier_nodes(self, tree)
    rearrange_layer_nodes(layer)
    reconnect_layer_nodes(layer)


def add_new_normalmap_modifier(ch, layer, modifier_type):
    """Creates and adds a new normal map modifier to a channel.

    Creates a new modifier instance at the beginning of the modifiers list,
    sets its type, and initializes its associated nodes in the node tree.
    F-curves are shifted down to accommodate the new modifier.

    Args:
        ch: The channel to add the modifier to.
        layer: The layer containing the channel.
        modifier_type (str): The type of modifier to create ('INVERT' or 'MATH').

    Returns:
        None
    """
    tree = get_tree(layer)

    name = [mt[1] for mt in normalmap_modifier_type_items if mt[0] == modifier_type][0]

    m = ch.modifiers_1.add()
    m.name = get_unique_name(name, ch.modifiers_1)
    ch.modifiers_1.move(len(ch.modifiers_1) - 1, 0)
    shift_normal_modifier_fcurves_down(ch)
    m = ch.modifiers_1[0]
    m.type = modifier_type

    check_modifier_nodes(m, tree)
