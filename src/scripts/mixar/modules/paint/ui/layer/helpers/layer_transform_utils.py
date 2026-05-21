# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Utility functions for layer transform operations.

This module provides shared utility functions for layer moving and grouping operations.
"""

from mixar.config.logging_config import get_logger

from ....core.element.update_fcurves import remap_layer_fcurves
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.io.input_outputs.input_outputs_layer_ios import check_layer_tree_ios
from ....core.layer.layer_utils import (
    get_layer_index_by_name,
    get_root_height_channel,
)
from ....core.node.check_nodes import check_all_layer_channel_io_and_nodes
from ....core.node.height_operations import update_displacement_height_ratio
from ...list_item.list_item_operators_helper import refresh_list_items

logger = get_logger(__name__)


def validate_layer_hierarchy(mp):
    """Validate and fix layer hierarchy to ensure only GROUPs have children.

    This function checks all layers and ensures:
    1. No layer has a parent that is not a GROUP type
    2. GROUP layers are always at root level (cannot be nested)

    If an invalid parent relationship is found, it is corrected by setting
    parent_idx to -1 (root level).

    Args:
        mp: The MPaint property group containing layers.

    Returns:
        bool: True if hierarchy was valid, False if corrections were made.
    """
    was_valid = True

    for layer in mp.layers:
        # GROUP layers must ALWAYS be at root level
        if layer.type == 'GROUP' and layer.parent_idx != -1:
            logger.warning(
                f"GROUP layer '{layer.name}' was nested inside another group. "
                f"Groups cannot be nested. Setting to root level."
            )
            layer.parent_idx = -1
            was_valid = False
            continue

        if layer.parent_idx >= 0:
            # Validate parent index is in bounds
            if layer.parent_idx >= len(mp.layers):
                logger.warning(
                    f"Layer '{layer.name}' has invalid parent_idx {layer.parent_idx} "
                    f"(out of bounds). Setting to root level."
                )
                layer.parent_idx = -1
                was_valid = False
                continue

            # Validate parent is a GROUP type
            parent = mp.layers[layer.parent_idx]
            if parent.type != 'GROUP':
                logger.warning(
                    f"Layer '{layer.name}' has non-GROUP parent '{parent.name}' "
                    f"(type: {parent.type}). Setting to root level."
                )
                layer.parent_idx = -1
                was_valid = False

    return was_valid


def is_valid_parent(mp, parent_name):
    """Check if a layer name refers to a valid GROUP parent.

    Args:
        mp: The MPaint property group containing layers.
        parent_name: Name of the potential parent layer, or None for root.

    Returns:
        bool: True if parent_name is None (root) or refers to a GROUP layer.
    """
    if parent_name is None:
        return True

    for layer in mp.layers:
        if layer.name == parent_name:
            return layer.type == 'GROUP'

    return False


def finalize_layer_move(context, node, mp, layer_name, parent_dict, index_dict):
    """Finalize layer move by remapping parents, updating nodes, and refreshing UI.

    This helper function contains shared logic for all layer move operations.

    Args:
        context: Blender context.
        node: The active mpaint node.
        mp: The node tree's mp property group.
        layer_name: Name of the moved layer (to update active layer selection).
        parent_dict: Dictionary mapping layer names to parent names.
        index_dict: Dictionary mapping layer names to original indices.

    Returns:
        bool: True if finalization succeeded, False otherwise.
    """
    from .layer_ui_helpers import recheck_background_layers_ios
    from ...list_item.list_item_operators_helper import get_layer_item_index

    wm = context.window_manager

    # Remap parents - but first validate that parent assignments are valid
    for lay in mp.layers:
        # GROUP layers must always be at root level - never assign a parent
        if lay.type == 'GROUP':
            lay.parent_idx = -1
            continue

        parent_name = parent_dict[lay.name]
        # Only set parent if it's a valid GROUP (or None for root)
        if is_valid_parent(mp, parent_name):
            lay.parent_idx = get_layer_index_by_name(mp, parent_name)
        else:
            logger.warning(
                f"Attempted to set non-GROUP '{parent_name}' as parent of '{lay.name}'. "
                f"Setting to root level instead."
            )
            lay.parent_idx = -1

    # Validate hierarchy integrity (in case of any edge cases)
    validate_layer_hierarchy(mp)

    # Remap fcurves
    remap_layer_fcurves(mp, index_dict)

    # Find new index of moved layer and update active layer
    layer_found = False
    new_layer_idx = -1
    for i, lay in enumerate(mp.layers):
        if lay.name == layer_name:
            mp.active_layer_index = i
            new_layer_idx = i
            # Also update UI layer selection
            if hasattr(wm, 'mixar_ui'):
                wm.mixar_ui.active_layer_index = i
            layer_found = True
            break

    if not layer_found:
        logger.warning(f"Could not find layer '{layer_name}' after move")

    # Height calculation can be changed after moving layer
    height_root_ch = get_root_height_channel(mp)
    if height_root_ch:
        update_displacement_height_ratio(height_root_ch)

    # Background layers should update its ios
    recheck_background_layers_ios(mp, index_dict)

    # Update GROUP layer IOs and internal nodes to ensure they have proper inputs for child layers
    # This is critical when layers are moved into/out of groups
    for layer in mp.layers:
        if layer.type == 'GROUP':
            # Update tree IOs (creates/removes input/output sockets)
            check_all_layer_channel_io_and_nodes(layer)
            # Reconnect internal nodes
            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)

    # Also update the moved layer's IOs and connections (its has_parent status may have changed)
    for layer in mp.layers:
        if layer.name == layer_name:
            check_all_layer_channel_io_and_nodes(layer)
            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)
            break

    # Refresh layer channel blend nodes
    reconnect_mp_nodes(node.node_tree)
    rearrange_mp_nodes(node.node_tree)

    # Update list items - use repoint_active=False since we'll set it manually
    refresh_list_items(mp, repoint_active=False)

    # Manually update active_item_index based on our correctly set active_layer_index
    if new_layer_idx >= 0 and new_layer_idx < len(mp.layers):
        item_idx = get_layer_item_index(mp.layers[new_layer_idx])
        if item_idx >= 0:
            mp.active_item_index = item_idx

    # Update UI
    wm.mpui.need_update = True

    return layer_found
