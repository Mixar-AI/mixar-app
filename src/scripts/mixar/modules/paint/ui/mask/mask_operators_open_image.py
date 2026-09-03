# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Open image as mask operator.

This module contains the operator for opening images as layer masks.
"""

import os
import time

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    StringProperty,
)
from bpy_extras.io_utils import ImportHelper

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.get_elements import get_default_uv_name
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.layer.layer_utils import get_height_channel
from ...core.node.get_nodes import get_layer_source
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import (
    get_active_object,
    get_noncolor_name,
    get_operator_description,
    get_user_preferences,
)
from ...utils.common import is_object_work_with_uv
from ...utils.constants import (
    TEMP_UV,
    interpolation_type_items,
    mask_texcoord_type_items,
)
from ...utils.statics import mask_blend_type_items
from ..mask.mask_creation import add_new_mask
from ..other.base_operator import OpenImage


class MOpenImageAsMask(bpy.types.Operator, ImportHelper, OpenImage):
    """Open Image as Mask"""

    bl_idname = "wm.m_open_image_as_mask"
    bl_label = "Open Image as Mask"
    bl_options = {"REGISTER", "UNDO"}

    interpolation: EnumProperty(
        name="Image Interpolation Type",
        description="image interpolation type",
        items=interpolation_type_items,
        default="Linear",
    )

    texcoord_type: EnumProperty(
        name="Mask Coordinate Type",
        description="Mask Coordinate Type",
        items=mask_texcoord_type_items,
        default="UV",
    )

    uv_map: StringProperty(default="")
    uv_map_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    blend_type: EnumProperty(
        name="Blend", description="Blend type", items=mask_blend_type_items, default=3
    )

    source_input: EnumProperty(
        name="Source Input",
        description="Source data for mask input",
        items=(("RGB", "Color", ""), ("ALPHA", "Alpha", "")),
        default="RGB",
    )

    use_udim_detecting: BoolProperty(
        name="Detect UDIMs",
        description="Detect selected UDIM files and load all matching tiles.",
        default=True,
    )

    file_browser_filepath: StringProperty(default="")

    @classmethod
    def poll(cls, context):
        node = get_active_mpaint_node()
        return node and len(node.node_tree.mp.layers) > 0

    @classmethod
    def description(self, context, properties):
        return get_operator_description(self)

    def invoke(self, context, event):
        obj = get_active_object()
        if hasattr(context, "layer"):
            self.layer = context.layer
            mp = self.layer.id_data.mp
        else:
            node = get_active_mpaint_node()
            mp = node.node_tree.mp
            self.layer = mp.layers[mp.active_layer_index]

        if not is_object_work_with_uv(obj):
            self.texcoord_type = "Generated"

        # Use active uv layer name by default
        if obj.type == "MESH" and len(obj.data.uv_layers) > 0:

            self.uv_map = get_default_uv_name(obj, mp)

            # UV Map collections update
            self.uv_map_coll.clear()
            for uv in obj.data.uv_layers:
                if not uv.name.startswith(TEMP_UV):
                    self.uv_map_coll.add().name = uv.name

        # The default blend type for mask is multiply
        if len(self.layer.masks) == 0:
            self.blend_type = "MULTIPLY"

        # Default source input is always color for now
        self.source_input = "RGB"

        # Check if there's height channel and use cubic interpolation if there is one
        height_ch = get_height_channel(self.layer)
        if height_ch and height_ch.enable:
            self.interpolation = "Cubic"
        elif self.layer.type == "IMAGE":
            source = get_layer_source(self.layer)
            if source and source.image:
                self.interpolation = source.interpolation

        if self.file_browser_filepath != "":
            if get_user_preferences().skip_property_popups and not event.shift:
                return self.execute(context)
            return context.window_manager.invoke_props_dialog(self)

        return self.running_fileselect_modal(context, event)

    def check(self, context):
        return True

    def draw(self, context):
        obj = get_active_object()

        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # ========== IMAGE MASK SETUP SECTION ==========
        setup_box = main_col.box()
        setup_col = setup_box.column(align=False)

        # Header
        header_row = setup_col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Image Mask Setup", icon="IMAGE_DATA")

        setup_col.separator(factor=1.2)

        # Image file (if from file browser)
        if self.file_browser_filepath != "":
            image_row = setup_col.row(align=True)
            image_row.scale_y = 1.4
            image_split = image_row.split(factor=0.25, align=True)
            label_col = image_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Image:")
            image_info_col = image_split.column(align=True)
            image_info_col.label(
                text=os.path.basename(self.file_browser_filepath), icon="IMAGE_DATA"
            )

            setup_col.separator(factor=0.4)

        # Interpolation
        interp_row = setup_col.row(align=True)
        interp_row.scale_y = 1.4
        interp_split = interp_row.split(factor=0.25, align=True)
        label_col = interp_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Interpolation:")
        interp_split.prop(self, "interpolation", text="")

        setup_col.separator(factor=0.4)

        # Vector/Texcoord
        vector_row = setup_col.row(align=True)
        vector_row.scale_y = 1.4
        vector_split = vector_row.split(factor=0.25, align=True)
        label_col = vector_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Vector:")
        vector_value_col = vector_split.column(align=True)
        crow = vector_value_col.row(align=True)
        crow.prop(self, "texcoord_type", text="")
        if obj.type == "MESH" and self.texcoord_type == "UV":
            crow.prop_search(
                self, "uv_map", self, "uv_map_coll", text="", icon="GROUP_UVS"
            )

        setup_col.separator(factor=0.4)

        # Blend (if layer has masks)
        if len(self.layer.masks) > 0:
            blend_row = setup_col.row(align=True)
            blend_row.scale_y = 1.4
            blend_split = blend_row.split(factor=0.25, align=True)
            label_col = blend_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Blend:")
            blend_split.prop(self, "blend_type", text="")

            setup_col.separator(factor=0.4)

        # Image Channel
        channel_row = setup_col.row(align=True)
        channel_row.scale_y = 1.4
        channel_split = channel_row.split(factor=0.25, align=True)
        label_col = channel_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Image Channel:")
        channel_value_col = channel_split.column(align=True)
        crow = channel_value_col.row(align=True)
        crow.prop(self, "source_input", expand=True)

        setup_col.separator(factor=0.4)

        # Relative path checkbox
        relative_row = setup_col.row(align=True)
        relative_row.scale_y = 1.2
        relative_split = relative_row.split(factor=0.25, align=True)
        relative_split.label(text="")
        relative_col = relative_split.column(align=True)
        relative_col.prop(self, "relative")

        setup_col.separator(factor=0.4)

        # UDIM detecting checkbox
        udim_row = setup_col.row(align=True)
        udim_row.scale_y = 1.2
        udim_split = udim_row.split(factor=0.25, align=True)
        udim_split.label(text="")
        udim_col = udim_split.column(align=True)
        udim_col.prop(self, "use_udim_detecting")

        setup_col.separator(factor=0.4)

        setup_col.separator(factor=0.8)

    def execute(self, context):
        T = time.time()
        if not hasattr(self, "layer"):
            return {"CANCELLED"}

        layer = self.layer
        mp = layer.id_data.mp
        wm = context.window_manager
        mpui = wm.mpui
        obj = get_active_object()

        if self.file_browser_filepath == "":
            import_list, directory = self.generate_paths()
        else:
            if not os.path.isfile(self.file_browser_filepath):
                self.report(
                    {"ERROR"},
                    "There's no image with address '"
                    + self.file_browser_filepath
                    + "'!",
                )
                return {"CANCELLED"}
            import_list = [os.path.basename(self.file_browser_filepath)]
            directory = os.path.dirname(self.file_browser_filepath)

        ori_ui_type = bpy.context.area.type
        images = []
        skipped_paths = []
        try:
            bpy.context.area.type = "IMAGE_EDITOR"
            for path in import_list:
                # Validate path to prevent directory traversal attacks
                safe_path = os.path.normpath(os.path.join(directory, path))
                normalized_directory = os.path.normpath(directory)
                if not safe_path.startswith(normalized_directory + os.sep) and safe_path != normalized_directory:
                    logger.warning("Skipping potentially unsafe path: %s", path)
                    skipped_paths.append(path)
                    continue

                bpy.ops.image.open(
                    filepath=safe_path,
                    directory=directory,
                    relative_path=self.relative,
                    use_udim_detecting=self.use_udim_detecting,
                )
                image = bpy.context.space_data.image
                if image not in images:
                    images.append(image)
        finally:
            bpy.context.area.type = ori_ui_type

        # Report skipped paths to the user
        if skipped_paths:
            self.report(
                {"WARNING"},
                f"Skipped {len(skipped_paths)} file(s) with invalid paths"
            )

        for image in images:
            if self.relative and bpy.data.filepath != "":
                try:
                    image.filepath = bpy.path.relpath(image.filepath)
                except:
                    pass

            if (
                image.colorspace_settings.name != get_noncolor_name()
                and not image.is_dirty
            ):
                image.colorspace_settings.name = get_noncolor_name()

            # Add new mask
            mask = add_new_mask(
                layer,
                image.name,
                "IMAGE",
                self.texcoord_type,
                self.uv_map,
                image,
                "",
                blend_type=self.blend_type,
                source_input=self.source_input,
                interpolation=self.interpolation,
            )

        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        reconnect_mp_nodes(layer.id_data)
        rearrange_mp_nodes(layer.id_data)

        # Update UI (only when a mask was actually added, `mask` is otherwise
        # unbound when all paths were skipped)
        if images:
            wm.mpui.need_update = True
            wm.mpui.layer_ui.expand_masks = True
            mask.expand_content = True
            mask.expand_vector = True

        logger.info(
            "Image(s) opened as mask(s) in %s ms!",
            "{:0.2f}".format((time.time() - T) * 1000)
        )
        wm.mptimer.time = str(time.time())

        return {"FINISHED"}


# Classes for auto-registration by bootstrap
classes = (MOpenImageAsMask,)
