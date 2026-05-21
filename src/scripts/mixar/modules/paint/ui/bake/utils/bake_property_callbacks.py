# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Property callback functions for baking operations"""

import bpy

from ....core.lib.lib import channel_custom_icon_dict
from ....core.lib.lib_operations import get_icon
from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.node.node_utils import get_active_mpaint_node
from ....utils.blender_commons import get_active_material, get_user_preferences
from ...udim.udim_utils import get_udim_segment_tilenums, is_uvmap_udim


def get_resize_image_entity_and_image(self, context):
    """Get entity and image for resize operation.

    Parameters:
        self: Operator instance with layer_name and image_name properties
        context: Blender context

    Returns:
        tuple: (entity, image) where entity is layer/mask and image is Image datablock
    """
    mp = get_active_mpaint_node().node_tree.mp
    entity = mp.layers.get(self.layer_name)
    image = bpy.data.images.get(self.image_name)

    if entity:
        for mask in entity.masks:
            if mask.active_edit:
                entity = mask
                break

    return entity, image


def update_resize_image_tile_number(self, context):
    """Update width/height when tile number changes.

    Parameters:
        self: Operator instance with tile_number property
        context: Blender context

    Returns:
        None
    """
    entity, image = get_resize_image_entity_and_image(self, context)

    if image and image.source == "TILED":
        tile = image.tiles.get(int(self.tile_number))
        if tile:
            self.width = tile.size[0]
            self.height = tile.size[1]


def update_bake_channel_uv_map(self, context):
    """Auto-detect and update UDIM setting when UV map changes.

    Parameters:
        self: Operator instance with uv_map and use_udim properties
        context: Blender context

    Returns:
        None
    """
    if get_user_preferences().enable_auto_udim_detection:
        mat = get_active_material()
        objs = get_all_objects_with_same_materials(mat)
        self.use_udim = is_uvmap_udim(objs, self.uv_map)


def bake_vcol_channel_items(self, context):
    """Generate enum items for bake to vertex color channel selection.

    Parameters:
        self: Operator instance
        context: Blender context

    Returns:
        list: List of tuples (identifier, name, description, icon, index)
    """
    node = get_active_mpaint_node()
    mp = node.node_tree.mp

    items = []
    # Default option to do nothing
    items.append(("Do Nothing", "Do Nothing", "", "", 0))
    items.append(("Sort By Channel Order", "Sort By Channel Order", "", "", 1))

    for i, ch in enumerate(mp.channels):
        if not ch.enable_bake_to_vcol:
            continue
        # Add two spaces to prevent text from being translated
        text_ch_name = ch.name + "  "
        # Index plus one, minus one when read
        icon_name = channel_custom_icon_dict[ch.type]
        items.append((str(i + 2), text_ch_name, "", get_icon(icon_name), i + 2))

    return items


def merge_channel_items(self, context):
    """Generate enum items for merge channel selection from active layer.

    Parameters:
        self: Operator instance
        context: Blender context

    Returns:
        list: List of tuples (identifier, name, description, icon, index)
    """
    node = get_active_mpaint_node()
    mp = node.node_tree.mp
    layer = mp.layers[mp.active_layer_index]

    items = []

    counter = 0
    for i, ch in enumerate(mp.channels):
        if not layer.channels[i].enable:
            continue
        icon_name = channel_custom_icon_dict[ch.type]
        items.append((str(i), ch.name, "", get_icon(icon_name), counter))
        counter += 1

    return items


def udim_tilenum_items(self, context):
    """Generate enum items for UDIM tile number selection.

    Parameters:
        self: Operator instance with image_name and layer_name properties
        context: Blender context

    Returns:
        list: List of tuples (identifier, name, description, icon, index)
    """
    image = bpy.data.images.get(self.image_name)

    if image.yua.is_udim_atlas:
        mp = get_active_mpaint_node().node_tree.mp
        layer = mp.layers.get(self.layer_name)

        # Get entity
        entity = layer
        mask_entity = False
        for mask in layer.masks:
            if mask.active_edit:
                entity = mask
                mask_entity = True
                break

        segment_name = entity.segment_name if not entity.use_baked else entity.baked_segment_name
        segment = image.yua.segments.get(segment_name)

        tilenums = get_udim_segment_tilenums(segment)
    else:
        tilenums = [t.number for t in image.tiles]

    items = []

    for i, tilenum in enumerate(tilenums):
        items.append((str(tilenum), str(tilenum), '', 'IMAGE_DATA', i))

    return items
