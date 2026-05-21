# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""F-curve update operations for the paint module.

This module provides functions to update F-curves when entities (layers, channels,
masks, modifiers) are reordered, removed, or otherwise modified. It serves as the
main entry point and re-exports all F-curve operations from submodules.

Functions are organized into three categories:
- Swap operations: Exchange F-curves between two entities at different indices
- Shift operations: Move F-curve indices up or down when entities are added/removed
- Remove operations: Delete F-curves associated with entities
"""
import re

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...utils.common import get_mp_fcurves_and_drivers

# Re-export all swap functions for backward compatibility
from .swap_fcurves import (
    swap_channel_fcurves,
    swap_layer_channel_fcurves,
    swap_mask_fcurves,
    swap_mask_channel_fcurves,
    swap_modifier_fcurves,
    swap_normal_modifier_fcurves,
)

# Re-export all shift functions for backward compatibility
from .shift_fcurves import (
    shift_modifier_fcurves_down,
    shift_normal_modifier_fcurves_down,
    shift_modifier_fcurves_up,
    shift_normal_modifier_fcurves_up,
    shift_channel_fcurves,
    shift_mask_fcurves_up,
)

# Re-export all remove functions for backward compatibility
from .remove_fcurves import (
    remove_entity_fcurves,
    remove_channel_fcurves,
)

# Define __all__ to explicitly list all public exports
__all__ = [
    # Remap functions (defined in this module)
    'remap_layer_fcurves',
    # Swap functions
    'swap_channel_fcurves',
    'swap_layer_channel_fcurves',
    'swap_mask_fcurves',
    'swap_mask_channel_fcurves',
    'swap_modifier_fcurves',
    'swap_normal_modifier_fcurves',
    # Shift functions
    'shift_modifier_fcurves_down',
    'shift_normal_modifier_fcurves_down',
    'shift_modifier_fcurves_up',
    'shift_normal_modifier_fcurves_up',
    'shift_channel_fcurves',
    'shift_mask_fcurves_up',
    # Remove functions
    'remove_entity_fcurves',
    'remove_channel_fcurves',
]


def remap_layer_fcurves(mp, index_dict):
    """Remap layer F-curves to new indices based on a provided mapping dictionary.

    This function updates the data paths of F-curves and drivers when layers are reordered,
    ensuring animations remain associated with the correct layers after rearrangement.

    Args:
        mp: The MPaint node tree object containing layers with F-curves.
        index_dict (dict): Dictionary mapping layer names to their original indices.
                          Keys are layer names (str), values are original indices (int).

    Returns:
        None
    """

    fcurves = get_mp_fcurves_and_drivers(mp)
    swapped_fcurves = []

    for i, lay in enumerate(mp.layers):
        if lay.name not in index_dict:
            continue
        original_index = index_dict[lay.name]
        if original_index == i:
            continue

        for fc in fcurves:
            if fc in swapped_fcurves:
                continue
            m = re.match(r'^mp\.layers\[(\d+)\].*', fc.data_path)
            if m:
                index = int(m.group(1))

                if index == original_index:
                    fc.data_path = fc.data_path.replace(
                        'mp.layers[' + str(original_index) + ']',
                        'mp.layers[' + str(i) + ']'
                    )
                    swapped_fcurves.append(fc)
