# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev 360 Operators

Operators for Lookdev 360 texture generation UI: upload/remove reference images,
pick style images, restore materials. The generate operator is in
lookdev360_generate_op.py.
"""

import bpy
from bpy.types import Operator
import os

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.mixie_space_utils import show_generation_error
from ...core.generate_progress import start_progress, complete_progress, reset_progress

from ....common.utils.file_select_utils import file_select_guard, mark_file_select_executed
from ...core.lookdev360_paint_integration import remove_lookdev360_fill_layer
from ...core.image_lifecycle import remove_image_safely
from .lookdev360_generate_op import MIXIE_OT_lookdev360_generate  # noqa: F401 — re-export only

logger = get_logger(__name__)


def _get_lookdev360_props(scene):
    """Get lookdev360 tab properties from sidebar."""
    if hasattr(scene, 'mixie_moodboard_sidebar') and scene.mixie_moodboard_sidebar:
        sidebar = scene.mixie_moodboard_sidebar
        if hasattr(sidebar, 'tab_lookdev360'):
            return sidebar.tab_lookdev360
    return None


class MIXIE_OT_lookdev360_upload_reference(Operator):
    """Upload a reference image for style transfer"""

    bl_idname = "mixie.lookdev360_upload_reference"
    bl_label = "Upload Reference Image"
    bl_description = "Upload an image for PBR texture generation"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to the reference image file",
        subtype='FILE_PATH'
    )

    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tiff;*.webp",
        options={'HIDDEN'}
    )

    def invoke(self, context, event):
        if not file_select_guard(self, context):
            return {'FINISHED'}
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.filepath:
            self.report({'WARNING'}, "No file selected")
            return {'CANCELLED'}

        # Validate path
        try:
            filepath = os.path.abspath(os.path.realpath(self.filepath))
        except (OSError, ValueError) as e:
            self.report({'ERROR'}, f"Invalid file path: {e}")
            return {'CANCELLED'}

        if not os.path.isfile(filepath):
            self.report({'ERROR'}, f"File not found: {filepath}")
            return {'CANCELLED'}

        # Load the image
        try:
            img = bpy.data.images.load(filepath, check_existing=True)
            img.pack()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load image: {e}")
            return {'CANCELLED'}

        # Set as reference image in sidebar properties
        props = _get_lookdev360_props(context.scene)
        if props:
            props.reference_image = img
            props.reference_image_name = img.name
            if img.size[0] > 0 and img.size[1] > 0:
                props.reference_image_resolution = f"{img.size[0]} x {img.size[1]}"

        # Redraw UI
        for area in context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()

        self.report({'INFO'}, f"Added '{img.name}' as reference image")
        mark_file_select_executed(self)
        return {'FINISHED'}


class MIXIE_OT_lookdev360_remove_reference(Operator):
    """Remove the reference image"""

    bl_idname = "mixie.lookdev360_remove_reference"
    bl_label = "Remove Reference Image"
    bl_description = "Remove the style reference image"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = _get_lookdev360_props(context.scene)
        if props:
            old_img = getattr(props, 'reference_image', None)
            props.reference_image = None
            props.reference_image_name = ""
            props.reference_image_resolution = ""
            remove_image_safely(old_img)

        # Redraw UI
        for area in context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()

        self.report({'INFO'}, "Reference image removed")
        return {'FINISHED'}


class MIXIE_OT_lookdev360_pick_style_image(Operator):
    """Pick a style image file for Lookdev 360"""

    bl_idname = "mixie.lookdev360_pick_style_image"
    bl_label = "Pick Style Image"
    bl_description = "Select a style reference image file"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to the style image file",
        subtype='FILE_PATH'
    )

    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tiff;*.webp",
        options={'HIDDEN'}
    )

    def invoke(self, context, event):
        if not file_select_guard(self, context):
            return {'FINISHED'}
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.filepath:
            self.report({'WARNING'}, "No file selected")
            return {'CANCELLED'}

        # Validate path
        try:
            filepath = os.path.abspath(os.path.realpath(self.filepath))
        except (OSError, ValueError) as e:
            self.report({'ERROR'}, f"Invalid file path: {e}")
            return {'CANCELLED'}

        if not os.path.isfile(filepath):
            self.report({'ERROR'}, f"File not found: {filepath}")
            return {'CANCELLED'}

        # Load the image
        try:
            img = bpy.data.images.load(filepath, check_existing=True)
            img.pack()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load image: {e}")
            return {'CANCELLED'}

        # Set as style image
        context.scene.mixie_lookdev360_style_image = img

        self.report({'INFO'}, f"Selected '{img.name}' as style image")
        mark_file_select_executed(self)
        return {'FINISHED'}


class MIXIE_OT_lookdev360_restore_materials(Operator):
    """Remove AI-generated fill layer, keeping the paint system intact"""

    bl_idname = "mixie.lookdev360_restore_materials"
    bl_label = "Restore Materials"
    bl_description = "Remove the AI-generated texture layer while keeping the paint system"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from mixar.modules.paint.core.node.node_utils import (
            get_active_mpaint_node,
        )

        scene = context.scene

        # Get the layer name to remove
        layer_name = getattr(scene, 'mixie_lookdev360_layer_name', '')
        if not layer_name:
            # Try sidebar props
            props = _get_lookdev360_props(scene)
            if props and hasattr(props, 'layer_name'):
                layer_name = props.layer_name

        if not layer_name:
            self.report({'WARNING'}, "No Lookdev360 layer name found to restore")
            return {'CANCELLED'}

        # Get checkpoint to know which objects were affected
        checkpoint_json = getattr(scene, 'mixie_lookdev360_checkpoint', '')
        removed_count = 0

        if checkpoint_json:
            import json
            try:
                checkpoint = json.loads(checkpoint_json)
                obj_names = list(checkpoint.get("objects", {}).keys())
            except (json.JSONDecodeError, AttributeError):
                obj_names = []
        else:
            # Fallback: try all selected mesh objects
            obj_names = [
                obj.name for obj in context.selected_objects
                if obj.type == 'MESH'
            ]

        for obj_name in obj_names:
            obj = bpy.data.objects.get(obj_name)
            if not obj or obj.type != 'MESH':
                continue

            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            node = get_active_mpaint_node(obj)
            if not node or not node.node_tree:
                continue

            group_tree = node.node_tree
            mp = group_tree.mp

            if remove_lookdev360_fill_layer(mp, group_tree, layer_name):
                removed_count += 1

        if removed_count > 0:
            # Clear stored layer name and reset flags
            if hasattr(scene, 'mixie_lookdev360_layer_name'):
                scene.mixie_lookdev360_layer_name = ""
            if hasattr(scene, 'mixie_lookdev360_has_applied'):
                scene.mixie_lookdev360_has_applied = False

            # Reset sidebar property
            props = _get_lookdev360_props(scene)
            if props and hasattr(props, 'has_applied_materials'):
                props.has_applied_materials = False
            if props and hasattr(props, 'layer_name'):
                props.layer_name = ""

            # Redraw UI
            for area in context.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()

            self.report({'INFO'}, f"Removed Lookdev360 layer from {removed_count} object(s)")
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "No Lookdev360 layers found to remove")
            return {'CANCELLED'}


# Keep old name for backwards compatibility
class MIXIE_OT_lookdev360_restore(MIXIE_OT_lookdev360_restore_materials):
    """Alias for restore_materials (backwards compatibility)"""
    bl_idname = "mixie.lookdev360_restore"


classes = (
    MIXIE_OT_lookdev360_upload_reference,
    MIXIE_OT_lookdev360_remove_reference,
    MIXIE_OT_lookdev360_pick_style_image,
    MIXIE_OT_lookdev360_restore,
    MIXIE_OT_lookdev360_restore_materials,
)


def register():
    """Register operator classes"""
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    """Unregister operator classes"""
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        if not getattr(cls, "is_registered", False):
            continue
        try:
            unregister_class(cls)
        except (RuntimeError, ValueError):
            logger.debug("Lookdev 360 operator already unregistered: %s",
                         cls.__name__, exc_info=True)
