# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Temporary image baking operators for preview purposes"""

import bpy
from bpy.props import BoolProperty, CollectionProperty, StringProperty

from ....core.layer.layer_utils import get_active_layer, get_uv_layers
from ....core.node.node_utils import get_active_mpaint_node
from ....utils.blender_commons import get_active_object, get_user_preferences
from ....utils.constants import TEMP_UV
from ..utils.bake_common import BaseBakeOperator
from ..utils.bake_operators_helper import disable_temp_bake, temp_bake


class MBakeTempImage(bpy.types.Operator, BaseBakeOperator):
    bl_idname = "wm.m_bake_temp_image"
    bl_label = "Bake temporary image of layer"
    bl_description = (
        "Bake temporary image of layer, can be useful to prefent glitching with cycles"
    )
    bl_options = {"REGISTER", "UNDO"}

    uv_map: StringProperty(default="")
    uv_map_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    hdr: BoolProperty(name="32 bit Float", default=True)

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node()  # and hasattr(context, 'parent')

    def invoke(self, context, event):
        self.invoke_operator(context)

        obj = get_active_object()
        mpup = get_user_preferences()

        self.auto_cancel = False
        if not hasattr(context, "parent"):
            self.auto_cancel = True
            return self.execute(context)

        self.parent = context.parent

        if self.parent.type not in {"HEMI"}:
            self.auto_cancel = True
            return self.execute(context)

        # Use active uv layer name by default
        uv_layers = get_uv_layers(obj)

        # UV Map collections update
        self.uv_map_coll.clear()
        for uv in uv_layers:
            if not uv.name.startswith(TEMP_UV):
                self.uv_map_coll.add().name = uv.name

        if len(self.uv_map_coll) > 0:
            self.uv_map = self.uv_map_coll[0].name

        if get_user_preferences().skip_property_popups and not event.shift:
            return self.execute(context)

        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        main_col = layout.column(align=False)

        # ========== BAKE TEMP IMAGE ==========
        box = main_col.box()
        col = box.column(align=False)

        # Header
        header_row = col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Bake Temporary Image", icon="RENDER_STILL")

        col.separator(factor=1.2)

        # Width
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Width:")
        split.prop(self, "width", text="")
        col.separator(factor=0.4)

        # Height
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Height:")
        split.prop(self, "height", text="")
        col.separator(factor=0.4)

        # HDR
        row = col.row(align=True)
        row.scale_y = 1.2
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="32-bit Float:")
        split.prop(self, "hdr", text="")
        col.separator(factor=0.4)

        # UV Map
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="UV Map:")
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

        # Get entity from context.parent or fall back to active layer
        if hasattr(self, "parent"):
            entity = self.parent
        else:
            # Get active layer when context.parent is not available
            node = get_active_mpaint_node()
            if not node or not node.node_tree:
                self.report({"ERROR"}, "No active Mixar node found!")
                return {"CANCELLED"}

            mp = node.node_tree.mp
            entity = get_active_layer(mp)

            if not entity:
                self.report({"ERROR"}, "No active layer found!")
                return {"CANCELLED"}

        if entity.type not in {"HEMI"}:
            self.report({"ERROR"}, "This layer type is not supported (yet)!")
            return {"CANCELLED"}

        # Bake temp image
        image = temp_bake(
            context,
            entity,
            self.width,
            self.height,
            self.hdr,
            self.samples,
            self.margin,
            self.uv_map,
            margin_type=self.margin_type,
            bake_device=self.bake_device,
        )

        return {"FINISHED"}


class MDisableTempImage(bpy.types.Operator):
    bl_idname = "wm.m_disable_temp_image"
    bl_label = "Disable Baked temporary image of layer"
    bl_description = "Disable bake temporary image of layer"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() and hasattr(context, "parent")

    def execute(self, context):
        entity = context.parent
        if not entity.use_temp_bake:
            self.report({"ERROR"}, "This layer is not temporarily baked!")
            return {"CANCELLED"}

        disable_temp_bake(entity)

        return {"FINISHED"}


classes = (
    MBakeTempImage,
    MDisableTempImage,
)
