# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard ImageGen Popup Operators

Popup dialog and generate-and-close wrapper for the ImageGen feature.
"""

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty

from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE
from mixar.modules.moodboard.constants import GENERATE_BUTTON_SCALE_Y


# =============================================================================
# IMAGEGEN POPUP
# =============================================================================

class MIXIE_OT_imagegen_popup(Operator):
    """Open ImageGen popup dialog"""
    bl_idname = "mixie.imagegen_popup"
    bl_label = "Generate Image"
    bl_description = "Open AI image generation dialog"
    bl_options = {'REGISTER'}

    use_selected_images: BoolProperty(
        name="Use selected images as context",
        description="Include selected moodboard images as reference for generation",
        default=True,
        options={'SKIP_SAVE'}
    )

    _generation_started: bool = False

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return context.space_data and context.space_data.type == 'MIXIE'

    def invoke(self, context, event):
        self.use_selected_images = True
        self._generation_started = False

        # Store original values to restore on cancel
        self._original_prompt = context.scene.mixie_imagegen_prompt
        self._original_ref_count = len(context.scene.mixie_imagegen_ref_images)

        return context.window_manager.invoke_popup(self, width=450)

    def check(self, context):
        """Check if generation started - if so, close the popup."""
        if getattr(context.scene, 'mixie_imagegen_is_generating', False):
            self._generation_started = True
            return False
        return True

    def cancel(self, context):
        # Only restore values if generation didn't start
        if not self._generation_started:
            if hasattr(self, '_original_prompt'):
                context.scene.mixie_imagegen_prompt = self._original_prompt
            # Remove any ref images added during this popup session
            if hasattr(self, '_original_ref_count'):
                ref_images = context.scene.mixie_imagegen_ref_images
                while len(ref_images) > self._original_ref_count:
                    ref_images.remove(len(ref_images) - 1)

    def _get_selected_image_count(self, context):
        """Count selected images in moodboard"""
        count = 0
        for item in context.scene.mixie_moodboard_images:
            if item.selected:
                count += 1
        return count

    def draw(self, context):
        layout = self.layout

        layout.label(text="Generate Image", icon='IMAGE')
        layout.separator()

        # Prompt with + button for adding style image
        row = layout.row(align=True)
        prompt_row = row.row()
        prompt_row.activate_init = True
        prompt_row.prop(context.scene, "mixie_imagegen_prompt", text="")
        row.operator("mixie.imagegen_add_style_image", text="", icon='ADD')

        layout.separator()

        # Reference images section
        box = layout.box()
        box_col = box.column(align=True)

        # Checkbox for using selected images
        selected_count = self._get_selected_image_count(context)
        row = box_col.row()
        row.prop(self, "use_selected_images", text="")
        if selected_count > 0:
            row.label(text=f"Use {selected_count} selected image(s) as context")
        else:
            row.label(text="Use selected images as context")
            row.enabled = False

        # Show added reference images
        ref_images = context.scene.mixie_imagegen_ref_images
        for i, ref_item in enumerate(ref_images):
            if ref_item.image:
                row = box_col.row()
                row.label(text=ref_item.image.name, icon='IMAGE_DATA')
                op = row.operator("mixie.imagegen_remove_style_image", text="", icon='X')
                op.index = i

        # Settings in a box
        settings_box = layout.box()
        settings_col = settings_box.column(align=True)
        row = settings_col.row(align=True)
        row.prop(context.scene, "mixie_imagegen_style", text="")
        row.prop(context.scene, "mixie_imagegen_model", text="")
        row.operator("mixie.imagegen_refresh", text="", icon='FILE_REFRESH')

        row = settings_col.row(align=True)
        row.prop(context.scene, "mixie_imagegen_aspect_ratio", text="")
        if hasattr(context.scene, "mixie_imagegen_resolution"):
            row.prop(context.scene, "mixie_imagegen_resolution", text="")

        layout.separator()
        row = layout.row()
        row.scale_y = GENERATE_BUTTON_SCALE_Y
        op = row.operator("mixie.imagegen_generate_and_close", text="Generate", icon='PLAY')
        op.use_selected_images = self.use_selected_images

    def execute(self, context):
        return {'FINISHED'}


# =============================================================================
# IMAGEGEN GENERATE AND CLOSE
# =============================================================================

class MIXIE_OT_imagegen_generate_and_close(Operator):
    """Generate image and close the popup"""
    bl_idname = "mixie.imagegen_generate_and_close"
    bl_label = "Generate"
    bl_description = "Generate AI image and close popup"
    bl_options = {'REGISTER'}

    use_selected_images: BoolProperty(
        name="Use selected images",
        default=True
    )

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return context.space_data and context.space_data.type == 'MIXIE'

    def execute(self, context):
        prompt = context.scene.mixie_imagegen_prompt.strip()
        if not prompt:
            self.report({'WARNING'}, "Please enter a prompt")
            return {'CANCELLED'}

        # If not using selected images, deselect all before calling generate
        if not self.use_selected_images:
            for item in context.scene.mixie_moodboard_images:
                item.selected = False

        # Call the imagegen generate operator
        bpy.ops.mixie.imagegen_generate()

        # Clear prompt after submit
        context.scene.mixie_imagegen_prompt = ""

        # Force popup to close by triggering check
        context.area.tag_redraw()

        return {'FINISHED'}


# Only include classes if MIXIE space is available
classes = (
    MIXIE_OT_imagegen_popup,
    MIXIE_OT_imagegen_generate_and_close,
) if MIXIE_SPACE_AVAILABLE else ()
