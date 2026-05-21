# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image resizing operations for layers and masks"""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from ....core.element.update_uv import set_uv_neighbor_resolution
from ....core.layer.mappings import update_mapping
from ....core.node.get_nodes import get_entity_source
from ....core.node.node_utils import get_active_mpaint_node
from ...udim.udim_utils import get_udim_segment_tilenums
from ....utils.blender_commons import get_active_object
from ..utils.bake_common import BaseBakeOperator, resize_image
from ..utils.bake_operators_helper import (
    get_resize_image_entity_and_image,
    udim_tilenum_items,
    update_resize_image_tile_number,
)


class MResizeImage(bpy.types.Operator, BaseBakeOperator):
    bl_idname = "wm.m_resize_image"
    bl_label = "Resize Image Layer/Mask"
    bl_description = "Resize image of layer or mask"
    bl_options = {"REGISTER", "UNDO"}

    layer_name: StringProperty(default="")
    image_name: StringProperty(default="")

    width: IntProperty(name="Width", default=1024, min=1, max=16384)
    height: IntProperty(name="Height", default=1024, min=1, max=16384)

    all_tiles: BoolProperty(
        name="Resize All Tiles",
        description="Resize all tiles (when using UDIM atlas, only segment tiles will be resized)",
        default=False,
    )

    tile_number: EnumProperty(
        name="Tile Number",
        description="Tile number that will be resized",
        items=udim_tilenum_items,
        update=update_resize_image_tile_number,
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() and get_active_object().type == "MESH"

    def invoke(self, context, event):
        self.invoke_operator(context)

        entity, image = get_resize_image_entity_and_image(self, context)

        if image:
            self.width = image.size[0]
            self.height = image.size[1]

            if image.source == "TILED":
                tile = image.tiles.get(int(self.tile_number))
                if tile:
                    self.width = tile.size[0]
                    self.height = tile.size[1]

            elif entity and image.yia.is_image_atlas:
                segment = image.yia.segments.get(entity.segment_name)
                self.width = segment.width
                self.height = segment.height

        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        image = bpy.data.images.get(self.image_name)

        main_col = layout.column(align=False)

        # ========== RESIZE IMAGE ==========
        box = main_col.box()
        col = box.column(align=False)

        # Header
        header_row = col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Resize Image", icon="IMAGE_DATA")

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

        if image:
            if image.yia.is_image_atlas:
                # Samples
                row = col.row(align=True)
                row.scale_y = 1.4
                split = row.split(factor=0.25, align=True)
                label_col = split.column(align=True)
                label_col.alignment = "RIGHT"
                label_col.label(text="Samples:")
                split.prop(self, "samples", text="")
                col.separator(factor=0.4)

            if image.source == "TILED":
                # All Tiles
                row = col.row(align=True)
                row.scale_y = 1.2
                split = row.split(factor=0.25, align=True)
                label_col = split.column(align=True)
                label_col.alignment = "RIGHT"
                if image.yua.is_udim_atlas:
                    label_col.label(text="All Tiles:")
                    split.prop(self, "all_tiles", text="Resize All Atlas Segment Tiles")
                else:
                    label_col.label(text="All Tiles:")
                    split.prop(self, "all_tiles", text="")
                col.separator(factor=0.4)

                if not self.all_tiles:
                    # Tile Number
                    row = col.row(align=True)
                    row.scale_y = 1.4
                    split = row.split(factor=0.25, align=True)
                    label_col = split.column(align=True)
                    label_col.alignment = "RIGHT"
                    label_col.label(text="Tile Number:")
                    split.prop(self, "tile_number", text="")
                    col.separator(factor=0.4)

        col.separator(factor=0.8)
        main_col.separator(factor=0.8)

    def execute(self, context):
        if not self.is_cycles_exist(context):
            return {"CANCELLED"}

        mp = get_active_mpaint_node().node_tree.mp
        entity, image = get_resize_image_entity_and_image(self, context)

        if not entity or not image:
            self.report({"ERROR"}, "There is no active image!")
            return {"CANCELLED"}

        # Get original size
        segment = None
        if image.yia.is_image_atlas:
            segment = image.yia.segments.get(entity.segment_name)
            ori_width = segment.width
            ori_height = segment.height
        if image.source == "TILED":
            tile = image.tiles.get(int(self.tile_number))
            ori_width = tile.size[0]
            ori_height = tile.size[1]
        else:
            ori_width = image.size[0]
            ori_height = image.size[1]

        if ori_width == self.width and ori_height == self.height:
            self.report({"ERROR"}, "This image already had the same size!")
            return {"CANCELLED"}

        override_context = None
        space = None
        ori_space_image = None

        if not image.yia.is_image_atlas:

            tilenums = [int(self.tile_number)]
            if image.source == "TILED" and self.all_tiles:
                if image.yua.is_udim_atlas:
                    segment = image.yua.segments.get(entity.segment_name)
                    tilenums = get_udim_segment_tilenums(segment)
                else:
                    tilenums = [t.number for t in image.tiles]

            # Find IMAGE_EDITOR area from window (works from any panel context)
            image_editor_area = None
            if bpy.context.window:
                for area in bpy.context.window.screen.areas:
                    if area.type == 'IMAGE_EDITOR':
                        image_editor_area = area
                        break

            # If no IMAGE_EDITOR found, use any area and temporarily change it
            if not image_editor_area and bpy.context.window:
                for area in bpy.context.window.screen.areas:
                    if area.type in {'VIEW_3D', 'PROPERTIES'}:
                        image_editor_area = area
                        break

            if image_editor_area:
                ori_ui_type = image_editor_area.ui_type
                image_editor_area.ui_type = "UV"
                image_editor_area.spaces[0].image = image

                for tilenum in tilenums:
                    if image.source == "TILED":
                        tile = image.tiles.get(tilenum)
                        if not tile:
                            continue
                        image.tiles.active = tile

                    # Use context override for image.resize operator
                    with bpy.context.temp_override(area=image_editor_area, space_data=image_editor_area.spaces[0]):
                        bpy.ops.image.resize(size=(self.width, self.height))

                image_editor_area.ui_type = ori_ui_type
            else:
                self.report({'ERROR'}, "Could not find suitable area for image resize operation")
                return {'CANCELLED'}

        else:
            scaled_img, new_segment = resize_image(
                image,
                self.width,
                self.height,
                image.colorspace_settings.name,
                self.samples,
                0,
                segment,
                bake_device=self.bake_device,
                mp=mp,
            )

            if new_segment:
                entity.segment_name = new_segment.name
                source = get_entity_source(entity)
                source.image = scaled_img
                segment.unused = True
                update_mapping(entity)

        # Update UV neighbor resolution
        set_uv_neighbor_resolution(entity)

        # Refresh active layer
        mp.active_layer_index = mp.active_layer_index

        return {"FINISHED"}


classes = (MResizeImage,)
