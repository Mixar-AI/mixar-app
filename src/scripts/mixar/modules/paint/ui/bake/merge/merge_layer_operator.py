# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer merging operation"""

from mixar.config.logging_config import get_logger

import time

import bpy
from bpy.props import BoolProperty, EnumProperty

from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.node.node_utils import get_active_mpaint_node
from ....core.subtree.get_subtree import get_parent_dict
from ....utils.blender_commons import get_active_object
from ..utils.bake_common import BaseBakeOperator
from ..utils.bake_operators_helper import merge_channel_items

# Import from helper modules
from .merge_layer_execute import (
    finalize_merge,
    merge_image_layers,
    process_merge_vertex_color,
)
from .merge_layer_invoke import (
    check_dirty_images,
    set_default_channel_index,
    validate_height_channels,
    validate_layer_source,
    validate_merge_layer,
)
from .merge_layer_ui import draw_merge_layer_dialog

# Re-export all functions for backward compatibility
__all__ = [
    "MMergeLayer",
    # From merge_layer_invoke
    "validate_merge_layer",
    "validate_height_channels",
    "validate_layer_source",
    "set_default_channel_index",
    "check_dirty_images",
    # From merge_layer_ui
    "draw_merge_layer_dialog",
    # From merge_layer_execute
    "merge_image_layers",
    "process_merge_vertex_color",
    "finalize_merge",
]

logger = get_logger(__name__)


class MMergeLayer(bpy.types.Operator, BaseBakeOperator):
    bl_idname = "wm.m_merge_layer"
    bl_label = "Merge layer"
    bl_description = "Merge Layer"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction", items=(("UP", "Up", ""), ("DOWN", "Down", "")), default="UP"
    )

    channel_idx: EnumProperty(
        name="Channel",
        description="Channel for merge reference",
        items=merge_channel_items,
    )

    apply_modifiers: BoolProperty(
        name="Apply Layer Modifiers", description="Apply layer modifiers", default=False
    )

    apply_neighbor_modifiers: BoolProperty(
        name="Apply Neighbor Modifiers",
        description="Apply neighbor modifiers",
        default=True,
    )

    force_mix_blending: BoolProperty(
        name="Force Mix Blending",
        description="Force to use mix blending while merging so there's no missing parts on the merge result",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        group_node = get_active_mpaint_node()
        return (
            get_active_object()
            and group_node
            and len(group_node.node_tree.mp.layers) > 0
            and len(group_node.node_tree.mp.channels) > 0
        )

    def invoke(self, context, event):
        self.invoke_operator(context)

        node = get_active_mpaint_node()
        mp = self.mp = node.node_tree.mp

        # Get active layer
        layer_idx = self.layer_idx = mp.active_layer_index
        layer = self.layer = mp.layers[layer_idx]

        self.error_message = ""

        # Validate merge operation
        error = validate_merge_layer(self, mp, layer, self.direction)
        if error:
            self.error_message = error

        # Validate height channels if no error yet
        if not self.error_message and self.neighbor_layer:
            error = validate_height_channels(self, mp, layer, self.neighbor_layer)
            if error:
                self.error_message = error

        # Validate layer source
        self.source, error = validate_layer_source(layer)
        if error and not self.error_message:
            self.error_message = error

        if self.error_message != "":
            return self.execute(context)

        # Set default value for channel index
        set_default_channel_index(self, layer, self.neighbor_layer)

        # Check if there's any unsaved images
        self.any_dirty_images = check_dirty_images(self.neighbor_layer, layer)

        return context.window_manager.invoke_props_dialog(self, width=320)

    def check(self, context):
        return True

    def draw(self, context):
        draw_merge_layer_dialog(self, context)

    def execute(self, context):
        # Delayed import to avoid circular dependency
        from ...layer.helpers.layer_operation_helpers import remove_layer

        if not self.is_cycles_exist(context):
            return {"CANCELLED"}

        if hasattr(self, "error_message") and self.error_message != "":
            self.report({"ERROR"}, self.error_message)
            return {"CANCELLED"}

        T = time.time()

        node = get_active_mpaint_node()
        tree = node.node_tree
        mp = tree.mp
        obj = get_active_object()
        mat = obj.active_material
        objs = get_all_objects_with_same_materials(mat, True)

        # Localize variables
        layer = self.layer
        layer_idx = self.layer_idx
        neighbor_layer = self.neighbor_layer
        neighbor_idx = self.neighbor_idx

        # Get main reference channel
        main_ch = mp.channels[int(self.channel_idx)]
        ch = layer.channels[int(self.channel_idx)]
        neighbor_ch = neighbor_layer.channels[int(self.channel_idx)]

        # Get parent dict
        parent_dict = get_parent_dict(mp)

        merge_success = False

        if (
            layer.type == "IMAGE"
            and main_ch.type == "NORMAL"
            and ch.normal_map_type == "VECTOR_DISPLACEMENT_MAP"
        ):
            self.report({"ERROR"}, "Merging VDM layers is not supported yet!")
            return {"CANCELLED"}

        # Merge image layers
        if layer.type == "IMAGE" and layer.texcoord_type == "UV":
            merge_success = merge_image_layers(
                self,
                context,
                mp,
                tree,
                layer,
                layer_idx,
                neighbor_layer,
                neighbor_idx,
                main_ch,
                ch,
                mat,
                node,
                objs,
            )

        # Merge vertex color layers
        elif layer.type == "VCOL" and neighbor_layer.type == "VCOL":
            success, error_msg = process_merge_vertex_color(
                layer, neighbor_layer, layer_idx, neighbor_idx, ch, neighbor_ch, objs
            )
            if not success:
                self.report({"ERROR"}, error_msg)
                return {"CANCELLED"}
            merge_success = True

        else:
            self.report({"ERROR"}, "This kind of merge is not supported yet!")
            return {"CANCELLED"}

        if merge_success:
            finalize_merge(mp, tree, layer_idx, neighbor_idx, parent_dict, remove_layer)
        else:
            self.report({"ERROR"}, "Merge failed for some reason!")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            "Merging layers is done in "
            + "{:0.2f}".format(time.time() - T)
            + " seconds!",
        )

        return {"FINISHED"}
