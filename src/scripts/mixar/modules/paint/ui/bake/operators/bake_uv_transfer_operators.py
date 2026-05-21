# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UV transfer and remapping operations"""

from mixar.config.logging_config import get_logger

import time

import bpy
from bpy.props import BoolProperty, CollectionProperty, StringProperty

from ....core.element.get_elements import get_uv_layer_index
from ....core.element.update_uv import move_uv
from ....core.layer.layer_utils import get_root_height_channel, get_uv_layers
from ....core.material.get_materials import get_all_objects_with_same_materials
from ....core.node.node_utils import get_active_mpaint_node
from ....utils.blender_commons import get_active_material, get_active_object
from ....utils.constants import TEMP_UV
from ..utils.bake_common import (
    BaseBakeOperator,
    prepare_bake_settings,
    recover_bake_settings,
    remember_before_bake,
)
from ..utils.bake_operators_helper import (
    get_entities_to_transfer,
    set_entities_which_using_the_same_image_or_segment,
    transfer_uv,
)

logger = get_logger(__name__)


class MTransferSomeLayerUV(bpy.types.Operator, BaseBakeOperator):
    bl_idname = "wm.m_transfer_some_layer_uv"
    bl_label = "Transfer Some Layer UV"
    bl_description = "Transfer some layers/masks UV by baking it to other uv (this will take quite some time to finish)"
    bl_options = {"REGISTER", "UNDO"}

    from_uv_map: StringProperty(default="")
    uv_map: StringProperty(default="")
    uv_map_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    remove_from_uv: BoolProperty(
        name="Delete From UV",
        description="Remove 'From UV' from objects",
        default=False,
    )

    reorder_uv_list: BoolProperty(
        name="Reorder UV",
        description="Reorder 'To UV' so it will have the same index as 'From UV'",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return (
            get_active_mpaint_node() and get_active_object().type == "MESH"
        )  # and hasattr(context, 'layer')

    def invoke(self, context, event):
        self.invoke_operator(context)

        obj = self.obj = get_active_object()
        scene = self.scene = context.scene

        if hasattr(context, "mask"):
            self.entity = context.mask

        elif hasattr(context, "layer"):
            self.entity = context.layer

        # Use active uv layer name by default
        uv_layers = get_uv_layers(obj)

        # UV Map collections update
        self.uv_map_coll.clear()
        for uv in uv_layers:
            if not uv.name.startswith(TEMP_UV):
                self.uv_map_coll.add().name = uv.name

        self.from_uv_map = self.entity.uv_name

        return context.window_manager.invoke_props_dialog(self, width=320)

    def check(self, context):
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # ========== UV TRANSFER ==========
        box = main_col.box()
        col = box.column(align=False)

        # Header
        header_row = col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="UV Transfer Settings", icon="GROUP_UVS")

        col.separator(factor=1.2)

        # From UV
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="From UV:")
        split.prop_search(self, "from_uv_map", self, "uv_map_coll", text="", icon="GROUP_UVS")
        col.separator(factor=0.4)

        # To UV
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="To UV:")
        split.prop_search(self, "uv_map", self, "uv_map_coll", text="", icon="GROUP_UVS")
        col.separator(factor=0.4)

        # Samples
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Samples:")
        split.prop(self, "samples", text="")
        col.separator(factor=0.4)

        # Margin
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Margin:")
        margin_split = split.split(factor=0.4, align=True)
        margin_split.prop(self, "margin", text="")
        margin_split.prop(self, "margin_type", text="")
        col.separator(factor=0.4)

        # Remove From UV
        row = col.row(align=True)
        row.scale_y = 1.2
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Delete From:")
        split.prop(self, "remove_from_uv", text="")
        col.separator(factor=0.4)

        if self.remove_from_uv:
            row = col.row(align=True)
            row.scale_y = 1.2
            split = row.split(factor=0.25, align=True)
            label_col = split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Reorder UV:")
            split.prop(self, "reorder_uv_list", text="")
            col.separator(factor=0.4)

        col.separator(factor=0.8)
        main_col.separator(factor=0.8)

    def execute(self, context):
        if not self.is_cycles_exist(context):
            return {"CANCELLED"}

        T = time.time()

        if self.from_uv_map == "" or self.uv_map == "":
            self.report({"ERROR"}, "From or To UV Map cannot be empty!")
            return {"CANCELLED"}

        if self.from_uv_map == self.uv_map:
            self.report({"ERROR"}, "From and To UV cannot have same value!")
            return {"CANCELLED"}

        mat = get_active_material()
        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        objs = get_all_objects_with_same_materials(mat)

        # Check if all uv are available on all objects
        for obj in objs:
            uv_layers = get_uv_layers(obj)
            from_uv = uv_layers.get(self.from_uv_map)
            to_uv = uv_layers.get(self.uv_map)
            if not from_uv or not to_uv:
                self.report({"ERROR"}, "Some uvs are not found in some objects!")
                return {"CANCELLED"}

        # Prepare bake settings
        book = remember_before_bake(mp)
        prepare_bake_settings(
            book,
            objs,
            mp,
            samples=self.samples,
            margin=self.margin,
            uv_map=self.uv_map,
            bake_type="EMIT",
            bake_device=self.bake_device,
            margin_type=self.margin_type,
        )

        # Get entites to transfer
        entities = get_entities_to_transfer(mp, self.from_uv_map, self.uv_map)

        for entity in entities:
            if entity.type == "IMAGE":

                logger.info("TRANSFER UV: Transferring entity %s...", entity.name)
                transfer_uv(objs, mat, entity, self.uv_map)

            if entity.baked_source != "":
                logger.info("TRANSFER UV: Transferring baked entity %s...", entity.name)
                transfer_uv(objs, mat, entity, self.uv_map, is_entity_baked=True)

            if entity.uv_name != self.uv_map:
                entity.uv_name = self.uv_map

        # return {'FINISHED'}

        if self.remove_from_uv:
            for obj in objs:
                uv_layers = get_uv_layers(obj)
                ori_index = get_uv_layer_index(obj, self.from_uv_map)
                from_uv = uv_layers.get(self.from_uv_map)
                uv_layers.remove(from_uv)

                # Reorder UV
                if self.reorder_uv_list and ori_index != -1:
                    uv_index = get_uv_layer_index(obj, self.uv_map)
                    if ori_index > uv_index:
                        ori_index -= 1
                    move_uv(obj, uv_index, ori_index)

        # Recover bake settings
        recover_bake_settings(book, mp)

        # Check height channel uv
        height_ch = get_root_height_channel(mp)
        if height_ch and height_ch.main_uv == self.from_uv_map:
            height_ch.main_uv = self.uv_map
            # height_ch.enable_smooth_bump = height_ch.enable_smooth_bump

        # Refresh mapping and stuff
        mp.active_layer_index = mp.active_layer_index

        self.report(
            {"INFO"},
            "All layers and masks using "
            + self.from_uv_map
            + " are transferred to "
            + self.uv_map
            + " in "
            + "{:0.2f}".format(time.time() - T)
            + " seconds!",
        )

        return {"FINISHED"}


class MTransferLayerUV(bpy.types.Operator, BaseBakeOperator):
    bl_idname = "wm.m_transfer_layer_uv"
    bl_label = "Transfer Layer UV"
    bl_description = "Transfer Layer UV by baking it to other uv (this will take quite some time to finish)"
    bl_options = {"REGISTER", "UNDO"}

    uv_map: StringProperty(default="")
    uv_map_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    @classmethod
    def poll(cls, context):
        return (
            get_active_mpaint_node() and get_active_object().type == "MESH"
        )  # and hasattr(context, 'layer')

    def invoke(self, context, event):
        self.invoke_operator(context)

        obj = self.obj = get_active_object()
        scene = self.scene = context.scene

        if hasattr(context, "mask"):
            self.entity = context.mask

        elif hasattr(context, "layer"):
            self.entity = context.layer

        if not self.entity:
            return self.execute(context)

        # Use active uv layer name by default
        uv_layers = get_uv_layers(obj)

        # UV Map collections update
        self.uv_map_coll.clear()
        for uv in uv_layers:
            if not uv.name.startswith(TEMP_UV) and uv.name != self.entity.uv_name:
                self.uv_map_coll.add().name = uv.name

        return context.window_manager.invoke_props_dialog(self, width=320)

    def check(self, context):
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # ========== UV TRANSFER ==========
        box = main_col.box()
        col = box.column(align=False)

        # Header
        header_row = col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Transfer Layer UV", icon="GROUP_UVS")

        col.separator(factor=1.2)

        # Target UV
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Target UV:")
        split.prop_search(self, "uv_map", self, "uv_map_coll", text="", icon="GROUP_UVS")
        col.separator(factor=0.4)

        # Samples
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Samples:")
        split.prop(self, "samples", text="")
        col.separator(factor=0.4)

        # Margin
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Margin:")
        margin_split = split.split(factor=0.4, align=True)
        margin_split.prop(self, "margin", text="")
        margin_split.prop(self, "margin_type", text="")
        col.separator(factor=0.4)

        col.separator(factor=0.8)
        main_col.separator(factor=0.8)

    def execute(self, context):
        if not self.is_cycles_exist(context):
            return {"CANCELLED"}

        T = time.time()

        if not hasattr(self, "entity"):
            return {"CANCELLED"}

        if self.entity.type != "IMAGE" or self.entity.texcoord_type != "UV":
            self.report({"ERROR"}, "Only works with image layer/mask with UV Mapping")
            return {"CANCELLED"}

        if self.uv_map == "":
            self.report({"ERROR"}, "Target UV Map cannot be empty!")
            return {"CANCELLED"}

        if self.uv_map == self.entity.uv_name:
            self.report({"ERROR"}, "This layer/mask already use " + self.uv_map + "!")
            return {"CANCELLED"}

        mat = get_active_material()
        mp = self.entity.id_data.mp
        objs = get_all_objects_with_same_materials(mat)
        ori_uv_name = self.entity.uv_name

        # Prepare bake settings
        book = remember_before_bake(mp)
        prepare_bake_settings(
            book,
            objs,
            mp,
            samples=self.samples,
            margin=self.margin,
            uv_map=self.uv_map,
            bake_type="EMIT",
            bake_device=self.bake_device,
            margin_type=self.margin_type,
        )

        if self.entity.type == "IMAGE":
            # Set other entites uv that using the same image or segment
            set_entities_which_using_the_same_image_or_segment(self.entity, self.uv_map)

            # Transfer UV
            # for ent in entities:
            transfer_uv(objs, mat, self.entity, self.uv_map)

        if self.entity.baked_source != "":
            transfer_uv(objs, mat, self.entity, self.uv_map, is_entity_baked=True)

        # Recover bake settings
        recover_bake_settings(book, mp)

        # Refresh mapping and stuff
        mp.active_layer_index = mp.active_layer_index

        self.report(
            {"INFO"},
            self.entity.name
            + " UV is transferred from "
            + ori_uv_name
            + " to "
            + self.uv_map
            + " in "
            + "{:0.2f}".format(time.time() - T)
            + " seconds!",
        )

        return {"FINISHED"}


classes = (
    MTransferSomeLayerUV,
    MTransferLayerUV,
)
