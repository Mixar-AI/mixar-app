# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...core.layer.layer_utils import get_layer_index
from ...core.subtree.get_subtree import get_list_of_parent_ids


def get_layer_item_index(layer):
    """Get the list item index for a given layer.

    Searches through the list items to find the index of the item that
    corresponds to the specified layer.

    Args:
        layer: The layer object to find in the list items.

    Returns:
        int: The index of the layer in the list items, or -1 if not found.
    """
    mp = layer.id_data.mp

    layer_index = get_layer_index(layer)
    for i, item in enumerate(mp.list_items):
        if item.index == layer_index and item.type == 'LAYER':
            return i

    return -1

def get_collapsed_parent_item_index(layer):
    """Get the list item index of the nearest collapsed parent layer.

    Searches through the layer's parent hierarchy to find the first parent
    that has its subitems collapsed, and returns that parent's list item index.

    Args:
        layer: The layer object whose collapsed parent to find.

    Returns:
        int: The list item index of the collapsed parent layer, or -1 if no
            collapsed parent exists.
    """
    mp = layer.id_data.mp

    collapsed_parent = None
    for idx in reversed(get_list_of_parent_ids(layer)):
        parent = mp.layers[idx]
        if not parent.expand_subitems:
            collapsed_parent = parent
            break

    if collapsed_parent:
        return get_layer_item_index(collapsed_parent)

    return -1

def refresh_list_items(mp, repoint_active=False):
    """Rebuild the list items from layers, masks, and channel overrides.

    Clears and repopulates the list items collection based on the current
    layer hierarchy, respecting expand/collapse states. Optionally maintains
    or updates the active item selection.

    Args:
        mp: The MPaint property group containing layers and list items.
        repoint_active (bool, optional): If True, attempts to maintain the
            current active item selection after refresh. Defaults to False.
    """
    # Get current active item and its parent
    active_item_name = ''
    active_item_type = ''
    active_item_is_second_member = False
    active_collapsed_parent_item_index = -1
    if repoint_active:

        # If layer index is out of bound, point to last layer
        if mp.active_layer_index >= len(mp.layers) and len(mp.layers) != 0:
            layer = mp.layers[len(mp.layers)-1]

            if not layer.expand_subitems or not mp.enable_expandable_subitems:
                active_item_name = layer.name
                active_item_type = 'LAYER'
                active_collapsed_parent_item_index = get_collapsed_parent_item_index(layer)

            elif layer.expand_subitems and mp.enable_expandable_subitems:
                for mask in layer.masks:
                    if mask.active_edit:
                        active_item_name = mask.name
                        active_item_type = 'MASK'

                for i, ch in enumerate(layer.channels):
                    if not ch.enable: continue
                    root_ch = mp.channels[i]
                    if ch.override and ch.override_type != 'DEFAULT' and ch.active_edit:
                        active_item_name = layer.name + ' ' + root_ch.name
                        active_item_type = 'CHANNEL_OVERRIDE'

                    if root_ch.type == 'NORMAL' and ch.override_1 and ch.override_1_type != 'DEFAULT' and ch.active_edit_1:
                        active_item_name = layer.name + ' ' + root_ch.name + ' 1'
                        active_item_type = 'CHANNEL_OVERRIDE'
                        active_item_is_second_member = True

        # Get current item
        elif mp.active_item_index < len(mp.list_items):
            item = mp.list_items[mp.active_item_index]

            # Get corresponding layer
            layer_index = item.index if item.type == 'LAYER' else item.parent_index
            if layer_index < len(mp.layers):
                layer = mp.layers[layer_index]

                # Get collapsed parent item index
                active_collapsed_parent_item_index = get_collapsed_parent_item_index(layer)

                # Get current active item
                active_item_name = item.name
                active_item_type = item.type
                active_item_is_second_member = item.is_second_member

    # Reset list
    mp.list_items.clear()

    new_active_index = -1
    for i, layer in enumerate(mp.layers):

        # Check if layer is collapsed
        collapsed_parent_item_index = get_collapsed_parent_item_index(layer)
        if collapsed_parent_item_index != -1:
            if collapsed_parent_item_index == active_collapsed_parent_item_index:
                new_active_index = collapsed_parent_item_index
        else:

            item = mp.list_items.add()
            item.type = 'LAYER'
            item.index = i
            item.name = layer.name
            item.parent_index = layer.parent_idx

            layer_item_index = len(mp.list_items)-1

            if active_item_name == layer.name and active_item_type == 'LAYER':
                new_active_index = layer_item_index

            for j, ch in enumerate(layer.channels):

                root_ch = mp.channels[j]

                # Channel Override
                if (layer.expand_subitems and 
                    (root_ch.type != 'NORMAL' or ch.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}) and 
                    (ch.override and ch.override_type != 'DEFAULT') and
                    ch.enable and
                    mp.enable_expandable_subitems
                    ):
                    item = mp.list_items.add()
                    item.type = 'CHANNEL_OVERRIDE'
                    item.index = j
                    item.parent_index = i
                    item.parent_name = layer.name
                    item.name = layer.name + ' ' + root_ch.name

                    if (
                        # Select channel with active edit after expand subitems
                        (repoint_active and mp.active_layer_index == i and ch.active_edit) or 

                        # Select correct mask after other layer uncollapsing
                        (active_item_name == item.name and active_item_type == 'CHANNEL_OVERRIDE' and not active_item_is_second_member)
                    ):
                        new_active_index = len(mp.list_items)-1

                elif active_item_name == layer.name + ' ' + root_ch.name and active_item_type == 'CHANNEL_OVERRIDE':
                    new_active_index = layer_item_index

                # Channel Override 1 / Normal
                if (layer.expand_subitems and 
                    (root_ch.type == 'NORMAL' and ch.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'}) and 
                    (ch.override_1 and ch.override_1_type != 'DEFAULT') and
                    ch.enable and
                    mp.enable_expandable_subitems
                    ):
                    item = mp.list_items.add()
                    item.type = 'CHANNEL_OVERRIDE'
                    item.index = j
                    item.parent_index = i
                    item.parent_name = layer.name
                    item.name = layer.name + ' ' + root_ch.name + ' 1'
                    item.is_second_member = True

                    if (
                        # Select channel with active edit after expand subitems
                        (repoint_active and mp.active_layer_index == i and ch.active_edit_1) or 

                        # Select correct mask after other layer uncollapsing
                        (active_item_name == item.name and active_item_type == 'CHANNEL_OVERRIDE' and active_item_is_second_member)
                    ):
                        new_active_index = len(mp.list_items)-1

                elif active_item_name == layer.name + ' ' + root_ch.name + ' 1' and active_item_type == 'CHANNEL_OVERRIDE':
                    new_active_index = layer_item_index

            # Masks
            for j, mask in enumerate(layer.masks):

                if layer.expand_subitems and mask.enable and mp.enable_expandable_subitems:
                    item = mp.list_items.add()
                    item.type = 'MASK'
                    item.index = j
                    item.parent_index = i
                    item.parent_name = layer.name
                    item.name = mask.name

                    if (
                        # Select mask with active edit after expand subitems
                        (repoint_active and mp.active_layer_index == i and mask.active_edit) or 

                        # Select correct mask after other layer uncollapsing
                        (active_item_name == mask.name and active_item_type == 'MASK')
                    ):
                        new_active_index = len(mp.list_items)-1

                elif active_item_name == mask.name and active_item_type == 'MASK':
                    new_active_index = layer_item_index

    # If there's no new active index, set it active layer
    if new_active_index == -1 and mp.active_layer_index < len(mp.layers):
        new_active_index = get_layer_item_index(mp.layers[mp.active_layer_index])

    # Set new active index
    if new_active_index != -1:
        mp.active_item_index = new_active_index
