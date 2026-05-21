# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer duplicate operator for Mixar layers system."""

import re
import time

import bpy
from bpy.props import BoolProperty, IntProperty
from bpy.types import Operator

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.update_fcurves import remap_layer_fcurves
from ...core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_mp_nodes
from ...core.layer.check_layers import any_decal_inside_layer
from ...core.layer.get_entities import get_layer_images
from ...core.layer.layer_utils import get_layer_index_by_name
from ...core.node.create_nodes import new_node
from ...core.node.node_utils import copy_id_props, get_active_mpaint_node
from ...core.subtree.get_subtree import (
    get_index_dict,
    get_list_of_all_children_and_child_ids,
    get_parent_dict,
)
from ...utils.blender_commons import (
    get_active_object,
    get_unique_name,
    get_user_preferences,
)
from ..layer.helpers.layer_duplicate_helpers import duplicate_layer_nodes_and_images
from ..list_item.list_item_operators_helper import refresh_list_items
from ..utils.ui_refresh import request_ui_refresh


class LAYERS_OT_DuplicateLayer(Operator):
    """Duplicate the active layer"""

    bl_idname = "wm.m_duplicate_layer"
    bl_label = "Duplicate Layer"
    bl_description = "Duplicate the active layer"
    bl_options = {"REGISTER", "UNDO"}

    layer_idx: IntProperty(
        name="Layer Index",
        description="Index of the layer to duplicate. If -1, uses active layer",
        default=-1,
    )

    packed_duplicate: BoolProperty(
        name="Duplicate Packed Images",
        description="Duplicate packed images",
        default=True,
    )

    duplicate_blank: BoolProperty(
        name="Make Duplicated Images blank",
        description="Make duplicated images blank",
        default=False,
    )

    ondisk_duplicate: BoolProperty(
        name="Duplicate Images on disk",
        description="Duplicate images on disk, this will create copies of images sourced from external files",
        default=False,
    )

    set_new_decal_position: BoolProperty(
        name="Set New Decal Position to Cursor",
        description="Position decals at 3D Cursor when duplicating",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        group_node = get_active_mpaint_node()
        return (
            get_active_object()
            and group_node
            and len(group_node.node_tree.mp.layers) > 0
        )

    def invoke(self, context, event):
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        layer_idx = self.layer_idx if self.layer_idx >= 0 else mp.active_layer_index
        layer = mp.layers[layer_idx]

        self.any_packed_image = False
        self.any_ondisk_image = False
        self.any_decal = False

        if not self.duplicate_blank:
            self.any_packed_image = any(get_layer_images(layer, packed_only=True))
            self.any_ondisk_image = any(get_layer_images(layer, ondisk_only=True))
            self.any_decal = any_decal_inside_layer(layer)

            if get_user_preferences().skip_property_popups and not event.shift:
                return self.execute(context)

            if self.any_packed_image or self.any_ondisk_image or self.any_decal:
                return context.window_manager.invoke_props_dialog(self, width=200)

        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        col = layout.column(align=False)

        if self.any_packed_image:
            row = col.row(align=True)
            row.scale_y = 1.2
            row.prop(self, "packed_duplicate")

        if self.any_ondisk_image:
            row = col.row(align=True)
            row.scale_y = 1.2
            row.prop(self, "ondisk_duplicate")

        if self.any_decal:
            row = col.row(align=True)
            row.scale_y = 1.2
            row.prop(self, "set_new_decal_position")

    def execute(self, context):
        T = time.time()

        wm = context.window_manager
        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp

        # Get parent and index dict
        parent_dict = get_parent_dict(mp)
        index_dict = get_index_dict(mp)

        # Use provided layer index, or fall back to active layer
        layer_idx = self.layer_idx if self.layer_idx >= 0 else mp.active_layer_index
        layer = mp.layers[layer_idx]
        source_layer_name = layer.name

        # Get all children
        children, child_ids = get_list_of_all_children_and_child_ids(layer)

        # Collect relevant ids to duplicate
        relevant_layer_names = [layer.name]
        relevant_ids = [layer_idx]
        for child in children:
            relevant_layer_names.append(child.name)
        relevant_ids.extend(child_ids)

        # Halt update to prevent needless reconnection
        mp.halt_update = True

        # List of newly created ids
        created_ids = []
        created_layer_names = []

        # Duplicate all relevant layers
        for i, lname in enumerate(relevant_layer_names):
            # Create new layer
            new_layer = mp.layers.add()
            new_layer.name = get_unique_name(lname, mp.layers)

            # Get original layer
            l = mp.layers.get(lname)
            group_node = tree.nodes.get(l.group_node)

            # Copy layer props
            copy_id_props(l, new_layer, ["name"])

            # Duplicate groups
            new_group_node = new_node(
                tree, new_layer, "group_node", "ShaderNodeGroup", group_node.label
            )
            new_group_node.node_tree = group_node.node_tree

            # Duplicate group inputs
            source_node = tree.nodes.get(l.group_node)
            for inp in new_group_node.inputs:
                source_inp = source_node.inputs.get(inp.name)
                if source_inp:
                    inp.default_value = source_inp.default_value

            # Rename masks
            mask_names = [m.name for m in l.masks]
            for mask in new_layer.masks:
                if mask.type in {"VCOL"}:
                    continue
                m = re.match(r"^Mask\s.*\((.+)\)$", mask.name)
                if m:
                    old_layer_name = m.group(1)
                    if old_layer_name == lname:
                        mask.name = mask.name.replace(old_layer_name, new_layer.name)
                else:
                    mask.name = get_unique_name(mask.name, mask_names)
                    mask_names.append(mask.name)

            created_layer_names.append(new_layer.name)
            created_ids.append(len(mp.layers) - 1)

        # Duplicate data of newly created layers
        created_layers = [l for l in mp.layers if l.name in created_layer_names]
        duplicate_layer_nodes_and_images(
            tree,
            created_layers,
            packed_duplicate=self.packed_duplicate or self.duplicate_blank,
            duplicate_blank=self.duplicate_blank,
            ondisk_duplicate=self.ondisk_duplicate or self.duplicate_blank,
            set_new_decal_position=self.set_new_decal_position,
        )

        # Move duplicated layer to current index
        for i, idx in enumerate(created_ids):
            relevant_id = relevant_ids[i]
            mp.layers.move(idx, relevant_id)

        # Remap parent index
        for lay in mp.layers:
            if lay.name in parent_dict:
                lay.parent_idx = get_layer_index_by_name(mp, parent_dict[lay.name])

        # Remap fcurves
        remap_layer_fcurves(mp, index_dict)

        # Revert back halt update
        mp.halt_update = False

        # Rearrange and reconnect
        reconnect_mp_nodes(tree)
        rearrange_mp_nodes(tree)

        # Refresh active layer
        mp.active_layer_index = mp.active_layer_index

        # Update list items
        refresh_list_items(mp)

        # Request UI refresh
        request_ui_refresh()

        logger.info(
            "Layer %s is duplicated in %s ms!",
            source_layer_name,
            "{:0.2f}".format((time.time() - T) * 1000),
        )
        wm.mptimer.time = str(time.time())

        return {"FINISHED"}


# Classes for registration
classes = (
    LAYERS_OT_DuplicateLayer,
)
