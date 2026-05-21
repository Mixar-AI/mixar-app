# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer and channel update helper functions.

Functions for managing active layer and channel updates.
"""

import bpy

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.element.update_image import get_active_image_and_stuffs, set_active_paint_slot_entity
from ...core.element.update_uv import refresh_temp_uv
from ...core.element.update_vcol import set_active_vertex_color
from ...core.element.get_elements import get_active_vertex_color
from ...core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_mp_nodes
from ...core.layer.layer_utils import get_uv_layers
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...utils.blender_commons import (
    get_active_material,
    get_active_object,
    is_bl_newer_than,
    set_image_paint_canvas,
)

# Delayed import to avoid circular dependency
def _get_update_preview_mode():
    from .operators_helper_preview import update_preview_mode
    return update_preview_mode

def _get_update_layer_preview_mode():
    from .operators_helper_preview import update_layer_preview_mode
    return update_layer_preview_mode


def update_active_mp_channel(self, context):
    """Update when active mpaint channel changes.

    Updates preview modes, active paint slot, and active UV layer when
    the active channel index changes.

    Args:
        self: Property that was updated.
        context: Blender context.
    """
    obj = get_active_object()
    tree = self.id_data
    mp = tree.mp
    if len(mp.channels) == 0:
        return
    ch = mp.channels[mp.active_channel_index]

    if mp.preview_mode:
        _get_update_preview_mode()(mp, context)
    if mp.layer_preview_mode:
        _get_update_layer_preview_mode()(mp, context)

    # Set active baked image to paint slot
    set_active_paint_slot_entity(mp)

    if mp.use_baked:
        if obj.type == "MESH":
            uv_layers = get_uv_layers(obj)

            baked_uv_map = uv_layers.get(mp.baked_uv_name)
            if baked_uv_map:
                uv_layers.active = baked_uv_map
                # NOTE: Blender 2.90 or lower need to use active render so the UV in image editor paint mode is updated
                if not is_bl_newer_than(2, 91):
                    baked_uv_map.active_render = True


def update_layer_index(self, context):
    """Update when active layer index changes.

    Updates active image, vertex color, UV layer, and texture paint mode when
    the active layer changes.

    Args:
        self: MPaint property group.
        context: Blender context.
    """
    #T = time.time()
    scene = context.scene
    if hasattr(bpy.context, 'object'): obj = get_active_object()
    elif is_bl_newer_than(2, 80): obj = bpy.context.view_layer.objects.active
    if not obj: return
    group_tree = self.id_data
    nodes = group_tree.nodes
    mpui = context.window_manager.mpui

    mp = self

    if (len(mp.layers) == 0 or mp.active_layer_index >= len(mp.layers) or mp.active_layer_index < 0):
        set_image_paint_canvas(None)
        return

    layer = mp.layers[mp.active_layer_index]

    # For Paint layers, check if we're selecting the layer itself (not a mask/channel)
    # If so, clear all active_edit flags so the layer's image is used
    if layer.type == 'IMAGE':
        # First check if the layer itself is selected (not a mask/channel)
        # by looking at the list_items
        is_layer_selected = True
        try:
            if (hasattr(mp, 'list_items') and hasattr(mp, 'active_item_index') and
                len(mp.list_items) > 0 and
                mp.active_item_index >= 0 and mp.active_item_index < len(mp.list_items)):
                item = mp.list_items[mp.active_item_index]
                if hasattr(item, 'type') and item.type in ('MASK', 'CHANNEL_OVERRIDE'):
                    is_layer_selected = False
        except (IndexError, AttributeError, ReferenceError):
            is_layer_selected = True

        # If layer itself is selected, clear all active_edit on masks/channels
        # This ensures the layer's image is used, not a mask's image
        # Use halt_update to prevent callback recursion
        if is_layer_selected:
            mp.halt_update = True
            for mask in layer.masks:
                mask.active_edit = False
            for ch in layer.channels:
                ch.active_edit = False
                ch.active_edit_1 = False
            mp.halt_update = False

    # Set active node to be layer group node so active keyframe can be visible on fcurve
    for i, l in enumerate(mp.layers):
        layer_node = group_tree.nodes.get(l.group_node)
        if layer_node:
            if i == mp.active_layer_index:
                layer_node.select = True
                #group_tree.nodes.active = layer_node
            else: layer_node.select = False

    if mp.layer_preview_mode: _get_update_layer_preview_mode()(mp, context)

    # Get active image and stuff
    image, uv_name, src_of_img, entity, mapping, vcol = get_active_image_and_stuffs(obj, mp)

    # Set active image to paint slot
    set_active_paint_slot_entity(mp)

    # Update active vertex color
    if vcol and get_active_vertex_color(obj) != vcol:
        set_active_vertex_color(obj, vcol)

    mat = get_active_material()
    objs = get_all_objects_with_same_materials(mat, selected_only=True)
    for ob in objs:
        refresh_temp_uv(ob, entity)

    # Switch modes based on layer type and selection
    layer = mp.layers[mp.active_layer_index]
    if layer.type == 'IMAGE':
        if obj and obj.type == 'MESH':
            # Switch to texture paint mode if not already
            if context.mode != 'PAINT_TEXTURE':
                try:
                    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
                except RuntimeError as e:
                    logger.warning(f"Could not switch to texture paint mode: {e}")

            # Set the canvas image if available
            if image:
                set_image_paint_canvas(image)

    elif layer.type in ('COLOR', 'GROUP'):
        # For Fill and Group layers, check if layer itself is selected (not a mask)
        is_layer_selected = True
        try:
            if (hasattr(mp, 'list_items') and hasattr(mp, 'active_item_index') and
                len(mp.list_items) > 0 and
                mp.active_item_index >= 0 and mp.active_item_index < len(mp.list_items)):
                item = mp.list_items[mp.active_item_index]
                if hasattr(item, 'type') and item.type in ('MASK', 'CHANNEL_OVERRIDE'):
                    is_layer_selected = False
        except (IndexError, AttributeError, ReferenceError):
            is_layer_selected = True

        # Switch to object mode when Fill/Group layer is selected (not mask)
        if is_layer_selected:
            if obj and obj.type == 'MESH' and context.mode != 'OBJECT':
                try:
                    bpy.ops.object.mode_set(mode='OBJECT')
                except RuntimeError as e:
                    logger.warning(f"Could not switch to object mode: {e}")

    # update_image_editor_image(context, image)


def update_sculpt_mode(self, context):
    """Update when sculpt mode changes.

    Args:
        self: Property that was updated.
        context: Blender context.
    """
    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)
