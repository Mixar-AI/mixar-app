# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer copy and paste operators for Mixar layers system."""

import time

import bpy
from bpy.props import BoolProperty, IntProperty
from bpy.types import Operator

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.update_fcurves import remap_layer_fcurves
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.layer.check_channels import check_start_end_root_ch_nodes
from ...core.layer.check_layers import any_decal_inside_layer
from ...core.layer.get_entities import get_layer_images
from ...core.layer.layer_utils import get_layer_index_by_name
from ...core.node.check_nodes import check_all_layer_channel_io_and_nodes, check_uv_nodes
from ...core.node.create_nodes import new_node
from ...core.node.node_utils import copy_id_props, get_active_mpaint_node
from ...core.subtree.get_subtree import (
    get_index_dict,
    get_list_of_all_children_and_child_ids,
    get_parent_dict,
    get_tree,
)
from ...utils.blender_commons import (
    get_active_object,
    get_unique_name,
    get_user_preferences,
)
from ...utils.common import get_channel_index
from ..layer.helpers.layer_duplicate_helpers import duplicate_layer_nodes_and_images
from ..list_item.list_item_operators_helper import refresh_list_items
from ..utils.ui_refresh import request_ui_refresh


class LAYERS_OT_CopyLayer(Operator):
    """Copy layer to clipboard"""

    bl_idname = "wm.m_copy_layer"
    bl_label = "Copy Layer"
    bl_description = "Copy the active layer to clipboard"
    bl_options = {"REGISTER", "UNDO"}

    layer_idx: IntProperty(
        name="Layer Index",
        description="Index of the layer to copy. If -1, uses active layer",
        default=-1,
    )

    all_layers: BoolProperty(
        name="Copy All Layers",
        description="Copy all layers instead of only the active one",
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

    def execute(self, context):
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        wmp = context.window_manager.mpprops

        # Use provided layer index, or fall back to active layer
        layer_idx = self.layer_idx if self.layer_idx >= 0 else mp.active_layer_index
        layer = mp.layers[layer_idx]

        wmp.clipboard_tree = node.node_tree.name
        wmp.clipboard_layer = layer.name if not self.all_layers else ""

        self.report({"INFO"}, f"Layer '{layer.name}' copied to clipboard")

        return {"FINISHED"}


class LAYERS_OT_PasteLayer(Operator):
    """Paste layer from clipboard"""

    bl_idname = "wm.m_paste_layer"
    bl_label = "Paste Layer"
    bl_description = "Paste layer from clipboard"
    bl_options = {"REGISTER", "UNDO"}

    packed_duplicate: BoolProperty(
        name="Duplicate Packed Images",
        description="Duplicate packed images",
        default=True,
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

    rebake_bakeds: BoolProperty(
        name="Rebake Baked Images",
        description="Rebake baked images",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        group_node = get_active_mpaint_node()
        if not group_node or not get_active_object():
            return False
        # Check if clipboard has content
        wmp = context.window_manager.mpprops
        return wmp.clipboard_tree != ""

    def invoke(self, context, event):
        group_node = get_active_mpaint_node()
        mp = group_node.node_tree.mp

        wm = context.window_manager
        wmp = wm.mpprops

        self.any_packed_image = False
        self.any_ondisk_image = False
        self.any_decal = False
        self.any_baked = False

        tree_source = bpy.data.node_groups.get(wmp.clipboard_tree)
        if tree_source:
            mp_source = tree_source.mp
            source_layers = []
            if wmp.clipboard_layer == "":
                source_layers = mp_source.layers
            else:
                layer = mp_source.layers.get(wmp.clipboard_layer)
                if layer:
                    source_layers.append(layer)

            for layer in source_layers:
                if not self.any_packed_image:
                    self.any_packed_image = any(
                        get_layer_images(layer, packed_only=True)
                    )
                if not self.any_ondisk_image:
                    self.any_ondisk_image = any(
                        get_layer_images(layer, ondisk_only=True)
                    )
                if not self.any_decal:
                    self.any_decal = any_decal_inside_layer(layer)

                # Do not check baked if current mp == mp_source
                if mp != mp_source:
                    if not self.any_baked:
                        self.any_baked = any(get_layer_images(layer, baked_only=True))

        if (
            self.any_packed_image
            or self.any_ondisk_image
            or self.any_decal
            or self.any_baked
        ):
            if get_user_preferences().skip_property_popups and not event.shift:
                return self.execute(context)

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

        if self.any_baked:
            row = col.row(align=True)
            row.scale_y = 1.2
            row.prop(self, "rebake_bakeds")

            if self.rebake_bakeds:
                col.separator()
                col.label(text="Rebaking can take a while", icon="ERROR")

    def execute(self, context):
        T = time.time()

        wm = context.window_manager
        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp
        wmp = wm.mpprops

        tree_source = bpy.data.node_groups.get(wmp.clipboard_tree)
        if not tree_source:
            self.report({"ERROR"}, "Cannot paste as clipboard source isn't found!")
            return {"CANCELLED"}

        mp_source = tree_source.mp

        # Check if the source mp has matching channel order
        matching = True
        if len(mp.channels) != len(mp_source.channels):
            matching = False
        else:
            for i, ch in enumerate(mp.channels):
                ch_source = mp_source.channels[i]
                if ch.name != ch_source.name or ch.type != ch_source.type:
                    matching = False
                    break

        if wmp.clipboard_layer == "":
            if len(mp_source.layers) == 0:
                self.report({"ERROR"}, "Copied tree has no layers!")
                return {"CANCELLED"}

            # Get datas
            first_copied_index = 0
            relevant_layer_names = [l.name for l in mp_source.layers]
        else:
            # Source layer
            layer_source = mp_source.layers.get(wmp.clipboard_layer)

            if not layer_source:
                self.report(
                    {"ERROR"},
                    "Cannot find copied layer! Maybe it was deleted or renamed.",
                )
                return {"CANCELLED"}

            # Check index of copied layer to know the offset
            first_copied_index = get_layer_index_by_name(mp_source, layer_source.name)

            # Get all children
            children, child_ids = get_list_of_all_children_and_child_ids(layer_source)

            # Collect relevant names
            relevant_layer_names = [layer_source.name]
            for child in children:
                relevant_layer_names.append(child.name)

        # Disable source layers if channel list is not matching
        ori_layer_enables = {}
        if not matching:
            for lname in relevant_layer_names:
                l = mp_source.layers.get(lname)
                ori_layer_enables[lname] = l.enable
                l.enable = False

        # Get parent and index dict
        parent_dict = get_parent_dict(mp)
        index_dict = get_index_dict(mp)

        # Current index
        cur_idx = mp.active_layer_index
        if len(mp.layers) > 0:
            cur_layer = mp.layers[cur_idx]
            cur_parent_idx = cur_layer.parent_idx
        else:
            cur_parent_idx = -1

        # List of newly pasted datas
        pasted_layer_names = []

        # Halt update to prevent needless reconnection
        mp.halt_update = True

        for lname in relevant_layer_names:
            ls = mp_source.layers.get(lname)

            # Create new layer
            new_layer = mp.layers.add()
            # Always generate a unique name to ensure mp.layers.get(name)
            # returns the newly pasted layer, not the source layer
            new_layer.name = get_unique_name(ls.name, mp.layers)

            # Get original source layer again to avoid pointer error after adding new layer
            ls = mp_source.layers.get(lname)

            # Copy layer props
            copy_id_props(ls, new_layer, ["name"])

            if not matching:
                # Clear out layer channel props
                new_layer.channels.clear()
                for mask in new_layer.masks:
                    mask.channels.clear()

                for root_ch in mp.channels:
                    # New layer channel
                    new_ch = new_layer.channels.add()
                    new_ch.enable = new_layer.type in {"GROUP", "BACKGROUND"}

                    # Get matching channel on source mp
                    source_idx = -1
                    if root_ch.name in mp_source.channels:
                        source_idx = get_channel_index(
                            mp_source.channels.get(root_ch.name)
                        )

                    # Copy layer channel props
                    if source_idx != -1:
                        copy_id_props(ls.channels[source_idx], new_ch)

                    for i, mask in enumerate(new_layer.masks):
                        # New mask channel
                        mch = mask.channels.add()
                        mch.enable = True  # Mask channel default is enabled

                        # Copy mask channel props
                        if source_idx != -1:
                            copy_id_props(ls.masks[i].channels[source_idx], mch)

                # Reenable new layer
                if ls.name in ori_layer_enables:
                    new_layer.enable = ori_layer_enables[ls.name]

            # Duplicate groups
            new_group_node = new_node(
                tree, new_layer, "group_node", "ShaderNodeGroup", new_layer.name
            )
            new_group_node.node_tree = get_tree(ls)

            # Duplicate group input values
            source_node = tree_source.nodes.get(ls.group_node)
            for inp in new_group_node.inputs:
                source_inp = source_node.inputs.get(inp.name)
                if source_inp:
                    inp.default_value = source_inp.default_value

            pasted_layer_names.append(new_layer.name)

        # Duplicate data of pasted layers
        pasted_layers = [l for l in mp.layers if l.name in pasted_layer_names]
        duplicate_layer_nodes_and_images(
            tree,
            pasted_layers,
            packed_duplicate=self.packed_duplicate,
            ondisk_duplicate=self.ondisk_duplicate,
            set_new_decal_position=self.set_new_decal_position,
        )

        # Move pasted layer to current index
        for i, lname in enumerate(pasted_layer_names):
            nl = mp.layers.get(lname)
            idx = get_layer_index_by_name(mp, lname)
            mp.layers.move(idx, cur_idx + i)

        for i, lname in enumerate(pasted_layer_names):
            nl = mp.layers.get(lname)

            # Remap parent index
            if i == 0:
                # Set upmost pasted layer to current parent index
                nl.parent_idx = cur_parent_idx
            else:
                if nl.parent_idx != -1:
                    nl.parent_idx += cur_idx - first_copied_index
                else:
                    nl.parent_idx = cur_parent_idx

            # Refresh io and nodes
            check_all_layer_channel_io_and_nodes(nl)

            reconnect_layer_nodes(nl)
            rearrange_layer_nodes(nl)

        # Remap parents for non pasted layers
        for lay in mp.layers:
            if lay.name in pasted_layer_names:
                continue
            lay.parent_idx = get_layer_index_by_name(mp, parent_dict[lay.name])

        # Remap fcurves
        remap_layer_fcurves(mp, index_dict)

        # Check uv maps
        check_uv_nodes(mp)

        # Revert back halt update
        mp.halt_update = False

        # Rearrange and reconnect
        check_start_end_root_ch_nodes(tree)
        reconnect_mp_nodes(tree)
        rearrange_mp_nodes(tree)

        # Revert original layer channel enables
        for lname, lenable in ori_layer_enables.items():
            l = mp_source.layers.get(lname)
            if l:
                l.enable = lenable

        # Rebake baked images
        if self.any_baked and self.rebake_bakeds:
            pasted_layer_ids = [
                i for i, l in enumerate(mp.layers) if l.name in pasted_layer_names
            ]
            try:
                bpy.ops.wm.m_rebake_specific_layers(layer_ids=str(pasted_layer_ids))
            except Exception as e:
                logger.warning(f"Failed to rebake layers: {e}")

            self.report(
                {"INFO"},
                "Rebaking pasted layers is done in "
                + "{:0.2f}".format(time.time() - T)
                + " seconds!",
            )

        # Refresh active layer
        mp.active_layer_index = mp.active_layer_index

        # Update list items
        refresh_list_items(mp)

        # Request UI refresh
        request_ui_refresh()

        logger.info(
            "Layer(s) pasted in %s ms!",
            "{:0.2f}".format((time.time() - T) * 1000),
        )
        wm.mptimer.time = str(time.time())

        return {"FINISHED"}


# Classes for registration
classes = (
    LAYERS_OT_CopyLayer,
    LAYERS_OT_PasteLayer,
)
