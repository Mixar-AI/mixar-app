# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ...utils.blender_commons import get_unique_name
from ..subtree.get_subtree import get_mask_tree
from ..node.create_nodes import new_mix_node, new_node
from ..node.node_utils import remove_node, copy_node_props

mask_modifier_type_items = (
    ('INVERT', 'Invert', 'Invert', 'MODIFIER', 0),
    ('RAMP', 'Ramp', '', 'MODIFIER', 1),
    ('CURVE', 'Curve', '', 'MODIFIER', 2),
)
mask_modifier_type_labels = {
    'INVERT' : 'Invert',
    'RAMP' : 'Ramp',
    'CURVE' : 'Curve',
}

can_be_expanded = {
    'RAMP',
    'CURVE',
}

def update_mask_modifier_enable(self, context):
    """Update callback for when a mask modifier's enable state changes.

    This function is triggered when a mask modifier is enabled or disabled. It updates
    the corresponding shader nodes in the node tree to reflect the new state by muting
    or unmuting nodes and adjusting their input values.

    Args:
        self: The mask modifier property group instance.
        context: The Blender context containing scene and UI state.

    Returns:
        None
    """
    mp = self.id_data.mp
    match = re.match(r'mp\.layers\[(\d+)\]\.masks\[(\d+)\]\.modifiers\[(\d+)\]', self.path_from_id())
    layer = mp.layers[int(match.group(1))]
    mask = layer.masks[int(match.group(2))]
    mod = self

    tree = get_mask_tree(mask)

    if mod.type == 'INVERT':
        invert = tree.nodes.get(mod.invert)
        if invert:
            invert.mute = not mod.enable
            invert.inputs[0].default_value = 1.0 if mod.enable else 0.0

    elif mod.type == 'RAMP':

        ramp_mix = tree.nodes.get(mod.ramp_mix)
        if ramp_mix:
            ramp_mix.mute = not mod.enable
            #ramp_mix.inputs[0].default_value = 1.0 if mod.enable else 0.0

    elif mod.type == 'CURVE':

        curve = tree.nodes.get(mod.curve)
        if curve:
            curve.mute = not mod.enable
            #curve.inputs[0].default_value = 1.0 if mod.enable else 0.0

def add_modifier_nodes(mod, tree, ref_tree=None):
    """Add shader nodes for a mask modifier to the specified node tree.

    Creates the necessary shader nodes based on the modifier type (INVERT, RAMP, or CURVE).
    If a reference tree is provided, node properties are copied from the reference nodes
    before they are removed.

    Args:
        mod: The mask modifier instance containing configuration and node references.
        tree: The target ShaderNodeTree where new nodes will be created.
        ref_tree (optional): A reference ShaderNodeTree containing existing nodes to copy
            properties from. Defaults to None.

    Returns:
        None
    """
    # Create the nodes
    if mod.type == 'INVERT':
        if ref_tree:
            invert_ref = ref_tree.nodes.get(mod.invert)

        invert = new_node(tree, mod, 'invert', 'ShaderNodeInvert', 'Invert')

        if ref_tree:
            copy_node_props(invert_ref, invert)
            ref_tree.nodes.remove(invert_ref)

    elif mod.type == 'RAMP':
        if ref_tree:
            ramp_ref = ref_tree.nodes.get(mod.ramp)
            ramp_mix_ref = ref_tree.nodes.get(mod.ramp_mix)

        ramp = new_node(tree, mod, 'ramp', 'ShaderNodeValToRGB', 'Ramp')
        ramp_mix = new_mix_node(tree, mod, 'ramp_mix', 'Ramp Mix', 'FLOAT')

        if ref_tree:
            copy_node_props(ramp_ref, ramp)
            copy_node_props(ramp_mix_ref, ramp_mix)

            ref_tree.nodes.remove(ramp_ref)
            ref_tree.nodes.remove(ramp_mix_ref)
        else:
            ramp_mix.inputs[0].default_value = 1.0

    elif mod.type == 'CURVE':
        if ref_tree:
            curve_ref = ref_tree.nodes.get(mod.curve)

        curve = new_node(tree, mod, 'curve', 'ShaderNodeRGBCurve', 'Curve')

        if ref_tree:
            copy_node_props(curve_ref, curve)

            ref_tree.nodes.remove(curve_ref)

def delete_mask_modifier_nodes(tree, mod):
    """Delete all shader nodes associated with a mask modifier from the node tree.

    Removes shader nodes created by the mask modifier based on its type. This includes
    invert nodes for INVERT type, ramp and ramp_mix nodes for RAMP type, and curve
    nodes for CURVE type.

    Args:
        tree: The ShaderNodeTree containing the nodes to be removed.
        mod: The mask modifier instance whose associated nodes should be deleted.

    Returns:
        None
    """
    if mod.type == 'INVERT':
        remove_node(tree, mod, 'invert')

    elif mod.type == 'RAMP':
        remove_node(tree, mod, 'ramp')
        remove_node(tree, mod, 'ramp_mix')

    elif mod.type == 'CURVE':
        remove_node(tree, mod, 'curve')

def add_new_mask_modifier(mask, modifier_type):
    """Create and add a new mask modifier to a mask.

    Creates a new mask modifier of the specified type, assigns it a unique name, and
    generates the corresponding shader nodes in the mask's node tree.

    Args:
        mask: The mask instance to which the new modifier will be added.
        modifier_type (str): The type of modifier to create. Must be one of:
            'INVERT', 'RAMP', or 'CURVE'.

    Returns:
        None
    """
    tree = get_mask_tree(mask)

    name = [mt[1] for mt in mask_modifier_type_items if mt[0] == modifier_type][0]

    m = mask.modifiers.add()
    m.name = get_unique_name(name, mask.modifiers)
    m.type = modifier_type

    add_modifier_nodes(m, tree)