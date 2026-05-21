# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image atlas operators module.

This module provides operators for managing image atlases, including:
- Creating and testing image atlas segments
- Converting between standard images and image atlases
- UV manipulation for transformed layers

Classes are split across multiple files for maintainability:
- image_atlas_operators.py (this file): Main module with test operators
- image_atlas_conversion_operators.py: Conversion operators
- image_atlas_uv_operators.py: UV-related operators
"""

import random
import time

import bpy
from bpy.props import EnumProperty, IntProperty

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.element.update_image import update_image_editor_image
from .image_atlas_utils import get_set_image_atlas_segment

# Re-export operators from submodules for backward compatibility
from .image_atlas_conversion_operators import (
    MConvertToImageAtlas,
    MConvertToStandardImage,
)
from .image_atlas_uv_operators import (
    MRefreshTransformedLayerUV,
    MBackToOriginalUV,
)


class MNewImageAtlasSegmentTest(bpy.types.Operator):
    """Test operator for creating new image atlas segments."""

    bl_idname = "wm.m_new_image_atlas_segment_test"
    bl_label = "New Image Atlas Segment Test"
    bl_description = "New Image Atlas segment test"
    bl_options = {"REGISTER", "UNDO"}

    color: EnumProperty(
        name="Altas Base Color",
        items=(
            ("WHITE", "White", ""),
            ("BLACK", "Black", ""),
            ("TRANSPARENT", "Transparent", ""),
        ),
        default="BLACK",
    )

    width: IntProperty(name="Width", default=128, min=1, max=4096)
    height: IntProperty(name="Height", default=128, min=1, max=4096)

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def check(self, context):
        return True

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # ========== ATLAS SETTINGS ==========
        box = main_col.box()
        col = box.column(align=False)

        # Header
        header_row = col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Atlas Settings", icon="IMAGE_DATA")

        col.separator(factor=1.2)

        # Color property
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Base Color:")
        split.prop(self, 'color', text="")

        col.separator(factor=0.4)

        # Width property
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Width:")
        split.prop(self, 'width', text="")

        col.separator(factor=0.4)

        # Height property
        row = col.row(align=True)
        row.scale_y = 1.4
        split = row.split(factor=0.25, align=True)
        label_col = split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Height:")
        split.prop(self, 'height', text="")

        col.separator(factor=0.4)

        col.separator(factor=0.8)  # Section end
        main_col.separator(factor=0.8)

    def execute(self, context):

        T = time.time()

        segment = get_set_image_atlas_segment(
            self.width, self.height, self.color, hdr=False
        )

        atlas_img = segment.id_data
        atlas = atlas_img.yia

        if segment and True:
            col = [random.random(), random.random(), random.random(), 1.0]

            start_x = self.width * segment.tile_x
            end_x = start_x + self.width

            start_y = self.height * segment.tile_y
            end_y = start_y + self.height

            pxs = list(atlas_img.pixels)

            for y in range(start_y, end_y):

                offset_y = atlas_img.size[0] * 4 * y

                for x in range(start_x, end_x):
                    for i in range(3):
                        pxs[offset_y + (x * 4) + i] = col[i]
                        pxs[offset_y + (x * 4) + 3] = 1.0

            atlas_img.pixels = pxs

        # Update image editor
        update_image_editor_image(context, atlas_img)

        logger.info(
            "Segment is created in %s ms!",
            "{:0.2f}".format((time.time() - T) * 1000)
        )

        return {"FINISHED"}


# Only register classes defined in this file
# Imported classes are registered by their source modules to avoid double registration
classes = (
    MNewImageAtlasSegmentTest,
)
