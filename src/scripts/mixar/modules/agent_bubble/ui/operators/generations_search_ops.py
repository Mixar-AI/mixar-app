# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Library tab's search row: pick a reference image, clear the search.

The query itself needs no operator: the pane's text field writes
``wm.mixar_generations_query`` and its update starts the search
(``core/library_search.py``). These two cover the chips beside it.
"""

import os

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from mixar.modules.common.i18n import n_

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".exr", ".hdr"}


class MIXAR_OT_generations_search_image(Operator):
    """Search the libraries for look-alikes of an image."""

    bl_idname = "mixar.generations_search_image"
    bl_label = "Search by Image"
    bl_description = (
        "Choose an image (a photo of the surface or object you want) and find the "
        "closest assets in your libraries"
    )
    bl_options = {'REGISTER'}

    filepath: StringProperty(name="Reference Image", subtype='FILE_PATH')
    filter_image: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, _event):
        # A native file picker: a props dialog opens behind the always-on-top
        # island window and looks like nothing happened.
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = os.path.abspath(bpy.path.abspath(self.filepath or ""))
        if not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in _IMAGE_EXTENSIONS:
            self.report({'ERROR'}, n_("Choose an image file"))
            return {'CANCELLED'}
        # The property update starts the search.
        context.window_manager.mixar_generations_search_ref = path
        return {'FINISHED'}


class MIXAR_OT_generations_search_clear(Operator):
    """Clear the Library search and show everything again."""

    bl_idname = "mixar.generations_search_clear"
    bl_label = "Clear Search"
    bl_description = "Clear the search text and image and show every asset again"
    bl_options = {'REGISTER'}

    def execute(self, context):
        from mixar.modules.agent_bubble.core import library_search

        library_search.clear(context.window_manager)
        return {'FINISHED'}


classes = (
    MIXAR_OT_generations_search_image,
    MIXAR_OT_generations_search_clear,
)
