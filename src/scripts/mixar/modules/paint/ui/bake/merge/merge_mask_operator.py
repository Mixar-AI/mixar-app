# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask merging operation"""

from mixar.config.logging_config import get_logger

import re
import time

import bpy

from ....core.element.update_image import copy_image_pixels
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes
from ....core.lib.lib import LINEAR_2_SRGB
from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.modifier.mask_modifier import delete_mask_modifier_nodes
from ....core.node.create_nodes import new_mix_node, replace_new_node
from ....core.node.get_nodes import get_active_mat_output_node, get_mask_source
from ....core.node.node_utils import get_active_mpaint_node, get_node_tree_lib, remove_node
from ....core.subtree.get_subtree import get_tree
from ....utils.blender_commons import (
    get_active_object,
    get_noncolor_name,
    remove_datablock,
    remove_mesh_obj,
    simple_remove_node,
)
from ....utils.constants import GAMMA, LAYER_ALPHA_VIEWER
from ...list_item.list_item_operators_helper import refresh_list_items
from ...mask.mask_operators_helper import remove_mask
from ..utils.bake_common import (
    BaseBakeOperator,
    bake_object_op,
    get_merged_mesh_objects,
    is_join_objects_problematic,
    prepare_bake_settings,
    recover_bake_settings,
    remember_before_bake,
)

logger = get_logger(__name__)


class MMergeMask(bpy.types.Operator, BaseBakeOperator):
    bl_idname = "wm.m_merge_mask"
    bl_label = "Merge mask"
    bl_description = "Merge Mask"
    bl_options = {"UNDO"}

    direction: bpy.props.EnumProperty(
        name="Direction", items=(("UP", "Up", ""), ("DOWN", "Down", "")), default="UP"
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node()

    def invoke(self, context, event):
        self.invoke_operator(context)

        layer = self.layer = context.layer
        mask = self.mask = context.mask

        # Get neighbor mask
        m = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", mask.path_from_id())
        index = int(m.group(2))
        if self.direction == "UP":
            try:
                neighbor_mask = layer.masks[index - 1]
            except:
                neighbor_mask = None
        else:
            try:
                neighbor_mask = layer.masks[index + 1]
            except:
                neighbor_mask = None

        # Check for any dirty images
        self.any_dirty_images = False
        if neighbor_mask:
            source = get_mask_source(mask)
            image = source.image if mask.type == "IMAGE" else None
            neighbor_image = (
                get_mask_source(neighbor_mask).image
                if neighbor_mask.type == "IMAGE"
                else None
            )

            if (image and image.is_dirty) or (
                neighbor_image and neighbor_image.is_dirty
            ):
                self.any_dirty_images = True

        if self.any_dirty_images:
            return context.window_manager.invoke_props_dialog(self, width=300)

        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        col = layout.column(align=True)
        col.label(text="Unsaved data will be LOST if you UNDO this operation.", icon="ERROR")
        col.label(text="Are you sure you want to continue?", icon="BLANK1")

    def check(self, context):
        return True

    def execute(self, context):
        if not self.is_cycles_exist(context):
            return {"CANCELLED"}

        T = time.time()

        mask = self.mask
        layer = self.layer
        mp = layer.id_data.mp
        obj = get_active_object()
        mat = obj.active_material
        scene = context.scene
        node = get_active_mpaint_node()

        # Get number of masks
        num_masks = len(layer.masks)
        if num_masks < 2:
            return {"CANCELLED"}

        # Get mask index
        m = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", mask.path_from_id())
        index = int(m.group(2))

        # Get neighbor index
        if self.direction == "UP" and index > 0:
            neighbor_idx = index - 1
        elif self.direction == "DOWN" and index < num_masks - 1:
            neighbor_idx = index + 1
        else:
            self.report({"ERROR"}, "No valid neighbor mask!")
            return {"CANCELLED"}

        if mask.type != "IMAGE":
            self.report({"ERROR"}, "Need image mask!")
            return {"CANCELLED"}

        # Get source
        source = get_mask_source(mask)
        if not source.image:
            self.report({"ERROR"}, "Mask image is missing!")
            return {"CANCELLED"}

        # Target image
        segment = None
        if source.image.yia.is_image_atlas and mask.segment_name != "":
            segment = source.image.yia.segments.get(mask.segment_name)
            if not segment:
                self.report({"ERROR"}, "Mask segment is missing!")
                return {"CANCELLED"}
            width = segment.width
            height = segment.height

            img = bpy.data.images.new(
                name="__TEMP",
                width=width,
                height=height,
                alpha=True,
                float_buffer=source.image.is_float,
            )

            if source.image.yia.color == "WHITE":
                img.generated_color = (1.0, 1.0, 1.0, 1.0)
            elif source.image.yia.color == "BLACK":
                img.generated_color = (0.0, 0.0, 0.0, 1.0)
            else:
                img.generated_color = (0.0, 0.0, 0.0, 0.0)

            img.colorspace_settings.name = get_noncolor_name()
        else:
            img = source.image.copy()
            width = img.size[0]
            height = img.size[1]

        # Activate layer preview mode
        ori_layer_preview_mode = mp.layer_preview_mode
        mp.layer_preview_mode = True

        # Get neighbor mask
        neighbor_mask = layer.masks[neighbor_idx]

        # Get layer tree
        tree = get_tree(layer)

        # Create mask mix nodes
        for m in [mask, neighbor_mask]:
            mix = new_mix_node(tree, m, "mix", "Mix")
            mix.blend_type = m.blend_type
            mix.inputs[0].default_value = m.intensity_value

            # Replace linear to more accurate ones
            linear = tree.nodes.get(m.linear)
            if linear:
                linear = replace_new_node(
                    tree, m, "linear", "ShaderNodeGroup", "Linear"
                )
                linear.node_tree = get_node_tree_lib(LINEAR_2_SRGB)

        # Reconnect nodes
        reconnect_layer_nodes(layer, merge_mask=True)
        rearrange_layer_nodes(layer)

        # Prepare to bake
        objs = get_all_objects_with_same_materials(mat, True)

        book = remember_before_bake(mp)
        prepare_bake_settings(
            book,
            objs,
            mp,
            samples=1,
            margin=5,
            uv_map=mask.uv_name,
            bake_type="EMIT",
            bake_device=self.bake_device,
        )

        # Combine objects if possible
        temp_objs = []
        if len(objs) > 1 and not is_join_objects_problematic(mp):
            objs = temp_objs = [get_merged_mesh_objects(scene, objs)]

        # Get material output
        output = get_active_mat_output_node(mat.node_tree)
        ori_bsdf = output.inputs[0].links[0].from_socket

        # Create bake nodes
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        emit = mat.node_tree.nodes.new("ShaderNodeEmission")

        # Set image
        tex.image = img
        mat.node_tree.nodes.active = tex

        # Connect
        mat.node_tree.links.new(node.outputs[LAYER_ALPHA_VIEWER], emit.inputs[0])
        mat.node_tree.links.new(emit.outputs[0], output.inputs[0])

        # return {'FINISHED'}

        # Bake
        bake_object_op()

        # Copy results to original image
        copy_image_pixels(img, source.image, segment)
        # Remove temp image
        remove_datablock(bpy.data.images, img, user=tex, user_prop="image")

        # Remove mask mix nodes
        for m in [mask, neighbor_mask]:
            remove_node(tree, m, "mix")

            # Replace linear to less accurate ones
            linear = tree.nodes.get(m.linear)
            if linear:
                linear = replace_new_node(
                    tree, m, "linear", "ShaderNodeGamma", "Linear"
                )
                linear.inputs[1].default_value = 1.0 / GAMMA

        # Remove modifiers
        for i, mod in reversed(list(enumerate(mask.modifiers))):
            delete_mask_modifier_nodes(tree, mod)
            mask.modifiers.remove(i)

        # Remove neighbor mask
        remove_mask(layer, neighbor_mask, obj, refresh_list=False)

        # Remove bake nodes
        simple_remove_node(mat.node_tree, tex)
        simple_remove_node(mat.node_tree, emit)

        # Recover original bsdf
        mat.node_tree.links.new(ori_bsdf, output.inputs[0])

        # Remove temporary objects
        if temp_objs:
            for o in temp_objs:
                remove_mesh_obj(o)

        # Recover bake settings
        recover_bake_settings(book, mp)

        # Revert back preview mode
        mp.layer_preview_mode = ori_layer_preview_mode

        # Point to neighbor mask for merge up
        if index > neighbor_idx:
            mask = layer.masks[neighbor_idx]

        # Set current mask as active
        mask.active_edit = True
        mp.active_layer_index = mp.active_layer_index

        # Refresh list items
        refresh_list_items(mp, repoint_active=True)

        self.report(
            {"INFO"},
            "Merging masks is done in "
            + "{:0.2f}".format(time.time() - T)
            + " seconds!",
        )

        return {"FINISHED"}
