# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from .list_item_operators_helper import refresh_list_items


def update_expand_subitems(self, context):
    """Update callback when expand subitems property changes.

    Refreshes list items while maintaining the active item selection.

    Args:
        self: The property that triggered the update.
        context: Blender context object.
    """
    mp = self.id_data.mp
    refresh_list_items(mp, repoint_active=True)

def update_list_item_index(self, context):
    """Update callback when the active list item index changes.

    Synchronizes the active item selection with the corresponding layer, mask,
    or channel override. Sets active_edit flags appropriately based on the
    selected item type.

    Args:
        self: The property that triggered the update.
        context: Blender context object.
    """
    try:
        mp = self.id_data.mp
        if mp.halt_update:
            return

        if mp.active_item_index < 0 or mp.active_item_index >= len(mp.list_items):
            return

        item = mp.list_items[mp.active_item_index]

        layer_index = -1
        canvas_image = None  # Store the image to set AFTER layer index update

        if item.type == 'LAYER':
            layer_index = item.index

            # Always clear active_edit on masks and channels when selecting the layer
            # Use halt_update to prevent callback recursion
            if layer_index < len(mp.layers):
                layer = mp.layers[layer_index]
                mp.halt_update = True
                for mask in layer.masks:
                    if mask.active_edit:
                        mask.active_edit = False
                for ch in layer.channels:
                    if ch.active_edit:
                        ch.active_edit = False
                    if ch.active_edit_1:
                        ch.active_edit_1 = False
                mp.halt_update = False

                # For Paint layers, store layer image to set after update_layer_index runs
                if layer.type == 'IMAGE':
                    from ...core.node.get_nodes import get_layer_source, get_tree
                    tree = get_tree(layer)
                    source = get_layer_source(layer, tree)
                    if source and hasattr(source, 'image') and source.image:
                        canvas_image = source.image

        elif item.type == 'MASK':
            layer_index = item.parent_index
            if layer_index < len(mp.layers):
                layer = mp.layers[layer_index]
                # Clear active_edit on all masks and channels first
                # Use halt_update to prevent callback recursion
                mp.halt_update = True
                for m in layer.masks:
                    if m.active_edit:
                        m.active_edit = False
                for ch in layer.channels:
                    if ch.active_edit:
                        ch.active_edit = False
                    if ch.active_edit_1:
                        ch.active_edit_1 = False
                # Set active_edit on the selected mask
                if item.index < len(layer.masks):
                    mask = layer.masks[item.index]
                    mask.active_edit = True

                    # Store mask image to set after update_layer_index runs
                    # For IMAGE masks, use the source image
                    # For baked masks, use the baked source image
                    # For procedural masks (not baked), clear the texture set
                    from ...core.node.get_nodes import get_mask_source
                    if mask.type == 'IMAGE':
                        source = get_mask_source(mask)
                        if source and hasattr(source, 'image') and source.image:
                            canvas_image = source.image
                        else:
                            canvas_image = 'CLEAR'  # Signal to clear texture set
                    elif mask.use_baked:
                        # Use baked image for procedural masks that have been baked
                        baked_source = get_mask_source(mask, get_baked=True)
                        if baked_source and hasattr(baked_source, 'image') and baked_source.image:
                            canvas_image = baked_source.image
                        else:
                            canvas_image = 'CLEAR'
                    else:
                        # Procedural mask without baked image - clear texture set
                        canvas_image = 'CLEAR'
                mp.halt_update = False

        elif item.type == 'CHANNEL_OVERRIDE':
            layer_index = item.parent_index
            if layer_index < len(mp.layers):
                layer = mp.layers[layer_index]
                # Clear active_edit on all masks and channels first
                # Use halt_update to prevent callback recursion
                mp.halt_update = True
                for m in layer.masks:
                    if m.active_edit:
                        m.active_edit = False
                for c in layer.channels:
                    if c.active_edit:
                        c.active_edit = False
                    if c.active_edit_1:
                        c.active_edit_1 = False
                # Set active_edit on the selected channel
                if item.index < len(layer.channels):
                    ch = layer.channels[item.index]
                    if not item.is_second_member:
                        ch.active_edit = True
                    else:
                        ch.active_edit_1 = True
                mp.halt_update = False

        if layer_index != -1 and layer_index < len(mp.layers):
            mp.active_layer_index = layer_index  # This triggers update_layer_index

        # Set canvas AFTER update_layer_index has run (to override any wrong image it might have set)
        if canvas_image:
            from ...utils.blender_commons import set_image_paint_canvas
            if canvas_image == 'CLEAR':
                set_image_paint_canvas(None)  # Clear texture set for procedural masks
            else:
                set_image_paint_canvas(canvas_image)
    except (IndexError, AttributeError, ReferenceError):
        pass  # Data in inconsistent state during list item changes

def get_active_item_entity(mp):
    """Get the actual entity (layer, mask, or channel) for the active list item.

    Retrieves the underlying layer, mask, or channel object that corresponds
    to the currently active list item.

    Args:
        mp: The MPaint property group containing list items and layers.

    Returns:
        Layer, Mask, Channel, or None: The corresponding entity object, or None
            if the active item index is invalid or the entity doesn't exist.
    """
    if mp.active_item_index >= len(mp.list_items) or len(mp.list_items) == 0:
        return None

    item = mp.list_items[mp.active_item_index]

    if item.type == 'LAYER':
        layer_index = item.index
        if layer_index < len(mp.layers):
            return mp.layers[layer_index]

    elif item.type == 'MASK':
        layer_index = item.parent_index
        if layer_index < len(mp.layers):
            layer = mp.layers[layer_index]
            if item.index < len(layer.masks):
                return layer.masks[item.index]

    elif item.type == 'CHANNEL_OVERRIDE':
        layer_index = item.parent_index
        if layer_index < len(mp.layers):
            layer = mp.layers[layer_index]
            if item.index < len(layer.channels):
                return layer.channels[item.index]

    return None

def set_active_entity_item(entity):
    """Set the active list item based on an entity (layer, mask, or channel).

    Determines the correct list item to activate based on the provided entity's
    path and the current state of expandable subitems. Handles layers, masks,
    and channel overrides.

    Args:
        entity: The layer, mask, or channel entity to set as active.
    """
    try:
        mp = entity.id_data.mp
    except (AttributeError, ReferenceError):
        return  # Entity data not available

    # Safety check for list_items availability
    if not hasattr(mp, 'list_items') or len(mp.list_items) == 0:
        return

    try:
        m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
        m2 = re.match(r'^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$', entity.path_from_id())
        m3 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())

        ch = None
        mask = None
        root_ch = None
        appendix = ''
        repoint_to_layer = False
        if m1:
            layer_idx = int(m1.group(1))
            if layer_idx >= len(mp.layers):
                return
            layer = mp.layers[layer_idx]
        elif m2:
            layer_idx = int(m2.group(1))
            ch_idx = int(m2.group(2))
            if layer_idx >= len(mp.layers):
                return
            layer = mp.layers[layer_idx]
            if ch_idx >= len(layer.channels) or ch_idx >= len(mp.channels):
                return
            ch = layer.channels[ch_idx]
            root_ch = mp.channels[ch_idx]

            if not mp.enable_expandable_subitems or not layer.expand_subitems or (not ch.active_edit_1 and not ch.active_edit):
                repoint_to_layer = True

            if ch.active_edit_1:
                appendix = ' 1'

        elif m3:
            layer_idx = int(m3.group(1))
            mask_idx = int(m3.group(2))
            if layer_idx >= len(mp.layers):
                return
            layer = mp.layers[layer_idx]
            if mask_idx >= len(layer.masks):
                return
            mask = layer.masks[mask_idx]

            if not mp.enable_expandable_subitems or not layer.expand_subitems or not mask.active_edit:
                repoint_to_layer = True

        else:
            return

        ori_halt_update = mp.halt_update
        if not mp.halt_update:
            mp.halt_update = True

        for i, item in enumerate(mp.list_items):
            if (
                ((m1 or repoint_to_layer) and item.type == 'LAYER' and item.name == layer.name) or
                (m2 and item.type == 'CHANNEL_OVERRIDE' and item.name == layer.name + ' ' + root_ch.name + appendix) or
                (m3 and item.type == 'MASK' and item.name == mask.name)
            ):
                if mp.active_item_index != i:
                    mp.active_item_index = i
                break

        if not ori_halt_update:
            mp.halt_update = False
    except (IndexError, AttributeError, ReferenceError):
        pass  # Data in inconsistent state, skip
