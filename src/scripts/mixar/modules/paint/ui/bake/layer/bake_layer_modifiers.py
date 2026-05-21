# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer modifier and transform management for baking operations"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.modifier.modifier_commons import delete_modifier_nodes
from ....core.subtree.get_subtree import get_mod_tree
from ....utils.blender_commons import get_active_object


# Import remove_mask from parent module to avoid circular dependency
def _lazy_import_remove_mask():
    """Lazy import to avoid circular dependency"""
    from ...mask.mask_operators_helper import remove_mask
    return remove_mask


def remember_and_disable_layer_modifiers_and_transforms(layer, disable_masks=False):
    """Store and disable layer modifiers, transitions, and masks for baking.

    Parameters:
        layer: Layer to process
        disable_masks (bool, optional): Whether to disable masks. Default False

    Returns:
        dict: Dictionary containing original states for later recovery
    """
    mp = layer.id_data.mp

    oris = {}

    oris["mods"] = []
    for mod in layer.modifiers:
        oris["mods"].append(mod.enable)
        mod.enable = False

    oris["ch_mods"] = {}
    oris["ch_trans_bumps"] = []
    oris["ch_trans_aos"] = []
    oris["ch_trans_ramps"] = []

    for i, c in enumerate(layer.channels):
        rch = mp.channels[i]
        ch_name = rch.name

        oris["ch_mods"][ch_name] = []
        for mod in c.modifiers:
            oris["ch_mods"][ch_name].append(mod.enable)
            mod.enable = False

        oris["ch_trans_bumps"].append(c.enable_transition_bump)
        oris["ch_trans_aos"].append(c.enable_transition_ao)
        oris["ch_trans_ramps"].append(c.enable_transition_ramp)

        if rch.type == "NORMAL":
            if c.enable_transition_bump:
                c.enable_transition_bump = False
        else:
            if c.enable_transition_ao:
                c.enable_transition_ao = False
            if c.enable_transition_ramp:
                c.enable_transition_ramp = False

    oris["masks"] = []
    for i, m in enumerate(layer.masks):
        oris["masks"].append(m.enable)
        if m.enable and disable_masks:
            m.enable = False

    return oris


def recover_layer_modifiers_and_transforms(layer, oris):
    """Restore layer modifiers, transitions, and masks from stored states.

    Parameters:
        layer: Layer to process
        oris (dict): Dictionary with original states from remember function

    Returns:
        None
    """
    mp = layer.id_data.mp

    # Recover original layer modifiers
    for i, mod in enumerate(layer.modifiers):
        mod.enable = oris["mods"][i]

    for i, c in enumerate(layer.channels):
        rch = mp.channels[i]
        ch_name = rch.name

        # Recover original channel modifiers
        for j, mod in enumerate(c.modifiers):
            mod.enable = oris["ch_mods"][ch_name][j]

        # Recover original channel transition effects
        if rch.type == "NORMAL":
            if oris["ch_trans_bumps"][i]:
                c.enable_transition_bump = oris["ch_trans_bumps"][i]
        else:
            if oris["ch_trans_aos"][i]:
                c.enable_transition_ao = oris["ch_trans_aos"][i]
            if oris["ch_trans_ramps"][i]:
                c.enable_transition_ramp = oris["ch_trans_ramps"][i]

    for i, m in enumerate(layer.masks):
        if oris["masks"][i] != m.enable:
            m.enable = oris["masks"][i]


def remove_layer_modifiers_and_transforms(layer):
    """Remove all modifiers, transitions, and masks from layer.

    Parameters:
        layer: Layer to process

    Returns:
        None
    """
    mp = layer.id_data.mp

    # Remove layer modifiers
    for i, mod in reversed(list(enumerate(layer.modifiers))):

        # Delete the nodes
        mod_tree = get_mod_tree(layer)
        delete_modifier_nodes(mod_tree, mod)
        layer.modifiers.remove(i)

    for i, c in enumerate(layer.channels):
        rch = mp.channels[i]
        ch_name = rch.name

        # Remove channel modifiers
        for j, mod in reversed(list(enumerate(c.modifiers))):

            # Delete the nodes
            mod_tree = get_mod_tree(c)
            delete_modifier_nodes(mod_tree, mod)
            c.modifiers.remove(j)

        # Remove channel transition effects
        if rch.type == "NORMAL" and c.enable_transition_bump:
            c.enable_transition_bump = False
            c.show_transition_bump = False
        else:
            if c.enable_transition_ao:
                c.enable_transition_ao = False
                c.show_transition_ao = False
            if c.enable_transition_ramp:
                c.enable_transition_ramp = False
                c.show_transition_ramp = False

    # Remove layer masks
    remove_mask = _lazy_import_remove_mask()
    for i, m in enumerate(layer.masks):
        remove_mask(layer, m, get_active_object())
