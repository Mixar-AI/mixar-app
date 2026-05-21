# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ...core.modifier.mask_modifier import mask_modifier_type_items
from ...core.node.create_nodes import new_mix_node, new_node
from ...core.node.node_utils import copy_node_props
from ...core.subtree.get_subtree import get_mask_tree
from ...utils.blender_commons import get_unique_name


def update_mask_modifier_enable(self, context):
    """Update callback for mask modifier enable property.

    Toggles the mute state of the modifier's nodes when the enable property changes.
    For INVERT modifiers, also sets the invert input value. For RAMP and CURVE
    modifiers, only mutes/unmutes the nodes.

    Args:
        self: The mask modifier property group being updated.
        context: Blender context object.

    Returns:
        None
    """
    mp = self.id_data.mp
    match = re.match(
        r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]\.modifiers\[(\d+)\]", self.path_from_id()
    )
    layer = mp.layers[int(match.group(1))]
    mask = layer.masks[int(match.group(2))]
    mod = self

    tree = get_mask_tree(mask)

    if mod.type == "INVERT":
        invert = tree.nodes.get(mod.invert)
        if invert:
            invert.mute = not mod.enable
            invert.inputs[0].default_value = 1.0 if mod.enable else 0.0

    elif mod.type == "RAMP":

        ramp_mix = tree.nodes.get(mod.ramp_mix)
        if ramp_mix:
            ramp_mix.mute = not mod.enable
            # ramp_mix.inputs[0].default_value = 1.0 if mod.enable else 0.0

    elif mod.type == "CURVE":

        curve = tree.nodes.get(mod.curve)
        if curve:
            curve.mute = not mod.enable
            # curve.inputs[0].default_value = 1.0 if mod.enable else 0.0


def add_modifier_nodes(mod, tree, ref_tree=None):
    """Create and add shader nodes for a mask modifier.

    Creates the appropriate shader nodes based on the modifier type (INVERT, RAMP,
    or CURVE). If a reference tree is provided, copies properties from the reference
    nodes and removes them from the reference tree.

    Args:
        mod: The mask modifier for which to create nodes.
        tree: The node tree where new nodes will be created.
        ref_tree (optional): Reference node tree containing existing nodes to copy
            properties from. Defaults to None.

    Returns:
        None
    """
    # Create the nodes
    if mod.type == "INVERT":
        if ref_tree:
            invert_ref = ref_tree.nodes.get(mod.invert)

        invert = new_node(tree, mod, "invert", "ShaderNodeInvert", "Invert")

        if ref_tree:
            copy_node_props(invert_ref, invert)
            ref_tree.nodes.remove(invert_ref)

    elif mod.type == "RAMP":
        if ref_tree:
            ramp_ref = ref_tree.nodes.get(mod.ramp)
            ramp_mix_ref = ref_tree.nodes.get(mod.ramp_mix)

        ramp = new_node(tree, mod, "ramp", "ShaderNodeValToRGB", "Ramp")
        ramp_mix = new_mix_node(tree, mod, "ramp_mix", "Ramp Mix", "FLOAT")

        if ref_tree:
            copy_node_props(ramp_ref, ramp)
            copy_node_props(ramp_mix_ref, ramp_mix)

            ref_tree.nodes.remove(ramp_ref)
            ref_tree.nodes.remove(ramp_mix_ref)
        else:
            ramp_mix.inputs[0].default_value = 1.0

    elif mod.type == "CURVE":
        if ref_tree:
            curve_ref = ref_tree.nodes.get(mod.curve)

        curve = new_node(tree, mod, "curve", "ShaderNodeRGBCurve", "Curve")

        if ref_tree:
            copy_node_props(curve_ref, curve)

            ref_tree.nodes.remove(curve_ref)


def add_new_mask_modifier(mask, modifier_type):
    """Add a new modifier to a mask with the specified type.

    Creates a new mask modifier, assigns it a unique name based on the modifier type,
    and creates the corresponding shader nodes in the mask's node tree.

    Args:
        mask: The mask to which the modifier will be added.
        modifier_type (str): The type of modifier to create (e.g., "INVERT", "RAMP", "CURVE").

    Returns:
        None
    """
    tree = get_mask_tree(mask)

    name = [mt[1] for mt in mask_modifier_type_items if mt[0] == modifier_type][0]

    m = mask.modifiers.add()
    m.name = get_unique_name(name, mask.modifiers)
    m.type = modifier_type

    add_modifier_nodes(m, tree)
