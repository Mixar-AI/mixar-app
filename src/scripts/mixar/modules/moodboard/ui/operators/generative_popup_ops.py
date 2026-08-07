# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Generative Feature Popup Operators

Popup dialogs for the pie menu generative features:
- Mesh Segment (description + expected parts)
- Lookdev (prompt only)
- Lookdev360 (prompt only)
- Image to 3D (prompt + model + style)

These popups close automatically when generation starts.
"""

import bpy
from bpy.types import Operator

from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE
from mixar.modules.moodboard.constants import GENERATE_BUTTON_SCALE_Y
from mixar.modules.moodboard.core.media_utils import is_still_item


# =============================================================================
# MESH SEGMENT POPUP
# =============================================================================

class MIXIE_OT_mesh_segment_popup(Operator):
    """Open Mesh Segment popup dialog"""
    bl_idname = "mixie.mesh_segment_popup"
    bl_label = "Mesh Segment"
    bl_description = "Open mesh segmentation dialog"
    bl_options = {'REGISTER'}

    _generation_started: bool = False

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return context.space_data and context.space_data.type == 'MIXIE'

    def invoke(self, context, event):
        # Store original values to restore on cancel
        self._original_description = context.scene.mixie_mesh_segment_description
        self._original_expected_parts = context.scene.mixie_mesh_segment_expected_parts
        self._generation_started = False

        return context.window_manager.invoke_popup(self, width=450)

    def check(self, context):
        """Check if generation started - if so, close the popup."""
        if getattr(context.scene, 'mixie_mesh_segment_is_processing', False):
            self._generation_started = True
            return False
        return True

    def cancel(self, context):
        # Only restore values if generation didn't start (user pressed Escape)
        if not self._generation_started:
            if hasattr(self, '_original_description'):
                context.scene.mixie_mesh_segment_description = self._original_description
            if hasattr(self, '_original_expected_parts'):
                context.scene.mixie_mesh_segment_expected_parts = self._original_expected_parts

    def draw(self, context):
        layout = self.layout

        layout.label(text="Mesh Segment", icon='MESH_DATA')
        layout.separator()

        row = layout.row()
        row.activate_init = True
        row.prop(context.scene, "mixie_mesh_segment_description", text="Description")

        layout.prop(context.scene, "mixie_mesh_segment_expected_parts", text="Expected Parts")

        layout.separator()
        row = layout.row()
        row.scale_y = GENERATE_BUTTON_SCALE_Y
        row.operator("mixie.mesh_segment_submit_and_close", text="Generate", icon='PLAY')

    def execute(self, context):
        return {'FINISHED'}


# =============================================================================
# LOOKDEV POPUP
# =============================================================================

class MIXIE_OT_lookdev_popup(Operator):
    """Open Lookdev popup dialog"""
    bl_idname = "mixie.lookdev_popup"
    bl_label = "Lookdev"
    bl_description = "Open lookdev generation dialog"
    bl_options = {'REGISTER'}

    _generation_started: bool = False

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return context.space_data and context.space_data.type == 'MIXIE'

    def invoke(self, context, event):
        # Store original values to restore on cancel
        self._original_prompt = context.scene.mixie_lookdev_prompt
        self._original_fast_mode = context.scene.mixie_moodboard_sidebar.tab_lookdev.fast_mode
        self._generation_started = False

        return context.window_manager.invoke_popup(self, width=450)

    def check(self, context):
        """Check if generation started - if so, close the popup."""
        if getattr(context.scene, 'mixie_lookdev_is_generating', False):
            self._generation_started = True
            return False
        return True

    def cancel(self, context):
        # Only restore values if generation didn't start
        if not self._generation_started:
            if hasattr(self, '_original_prompt'):
                context.scene.mixie_lookdev_prompt = self._original_prompt
            if hasattr(self, '_original_fast_mode'):
                context.scene.mixie_moodboard_sidebar.tab_lookdev.fast_mode = self._original_fast_mode

    def draw(self, context):
        layout = self.layout

        layout.label(text="Lookdev", icon='MATERIAL')
        layout.separator()

        row = layout.row()
        row.activate_init = True
        row.prop(context.scene, "mixie_lookdev_prompt", text="")

        # Fast mode option
        sidebar = context.scene.mixie_moodboard_sidebar
        tab = sidebar.tab_lookdev

        box = layout.box()
        box.prop(tab, "fast_mode", text="Fast Mode (lower quality, ~4x faster)")

        layout.separator()
        row = layout.row()
        row.scale_y = GENERATE_BUTTON_SCALE_Y
        row.operator("mixie.lookdev_generate_and_close", text="Generate", icon='PLAY')

    def execute(self, context):
        return {'FINISHED'}


# =============================================================================
# LOOKDEV360 POPUP
# =============================================================================

class MIXIE_OT_lookdev360_popup(Operator):
    """Open Lookdev360 popup dialog"""
    bl_idname = "mixie.lookdev360_popup"
    bl_label = "Generate PBR Maps"
    bl_description = "Open PBR texture map generation dialog"
    bl_options = {'REGISTER'}

    _generation_started: bool = False

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return context.space_data and context.space_data.type == 'MIXIE'

    def invoke(self, context, event):
        # Store original values to restore on cancel
        self._original_prompt = context.scene.mixie_lookdev360_prompt
        sidebar = context.scene.mixie_moodboard_sidebar
        tab = sidebar.tab_lookdev360
        self._original_style_only = tab.style_only
        self._original_resolution = tab.resolution
        self._generation_started = False

        return context.window_manager.invoke_popup(self, width=450)

    def check(self, context):
        """Check if generation started - if so, close the popup."""
        if getattr(context.scene, 'mixie_lookdev360_is_generating', False):
            self._generation_started = True
            return False
        return True

    def cancel(self, context):
        # Only restore values if generation didn't start
        if not self._generation_started:
            if hasattr(self, '_original_prompt'):
                context.scene.mixie_lookdev360_prompt = self._original_prompt
            sidebar = context.scene.mixie_moodboard_sidebar
            tab = sidebar.tab_lookdev360
            if hasattr(self, '_original_style_only'):
                tab.style_only = self._original_style_only
            if hasattr(self, '_original_resolution'):
                tab.resolution = self._original_resolution

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="Generate PBR Maps", icon='WORLD')
        layout.separator()

        # Prompt with + button for picking reference image (like ImageGen)
        sidebar = scene.mixie_moodboard_sidebar
        tab = sidebar.tab_lookdev360

        row = layout.row(align=True)
        prompt_row = row.row()
        prompt_row.activate_init = True
        prompt_row.prop(scene, "mixie_lookdev360_prompt", text="")
        row.operator("mixie.lookdev360_upload_reference", text="", icon='ADD')

        layout.separator()

        # Image input section in a box (like Image to 3D)
        box = layout.box()
        box_col = box.column(align=True)

        # Style only checkbox first
        box_col.prop(tab, "style_only", text="Use image only as style reference")

        box_col.separator()

        # Checkbox for using selected moodboard image
        box_col.prop(tab, "use_selected_image", text="Use Selected Moodboard Image")

        # Show current image info
        if tab.use_selected_image:
            selected = [
                item for item in scene.mixie_moodboard_images
                if item.selected and is_still_item(item)
            ]
            if selected:
                img = selected[0].image
                row = box_col.row()
                row.label(text=f"Selected: {img.name}", icon='CHECKMARK')
            else:
                row = box_col.row()
                row.label(text="No image selected in moodboard", icon='ERROR')
        else:
            # Show uploaded image if any
            if tab.reference_image:
                row = box_col.row(align=True)
                row.label(text=tab.reference_image.name, icon='IMAGE_DATA')
                row.operator("mixie.lookdev360_remove_reference", text="", icon='X')

        layout.separator()

        # Resolution dropdown
        row = layout.row()
        row.prop(tab, "resolution", text="Resolution")

        # Restore materials (conditional)
        if hasattr(tab, 'has_applied_materials') and tab.has_applied_materials:
            layout.separator()
            layout.operator("mixie.lookdev360_restore_materials", text="Restore Materials", icon='RECOVER_LAST')

        layout.separator()
        row = layout.row()
        row.scale_y = GENERATE_BUTTON_SCALE_Y
        row.operator("mixie.lookdev360_generate_and_close", text="Generate", icon='PLAY')

    def execute(self, context):
        return {'FINISHED'}


# =============================================================================
# IMAGE TO 3D POPUP
# =============================================================================

class MIXIE_OT_image_to_3d_popup(Operator):
    """Open Image to 3D popup dialog"""
    bl_idname = "mixie.image_to_3d_popup"
    bl_label = "Image to 3D"
    bl_description = "Open image to 3D model generation dialog"
    bl_options = {'REGISTER'}

    _generation_started: bool = False

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return context.space_data and context.space_data.type == 'MIXIE'

    def invoke(self, context, event):
        # Store original values to restore on cancel
        self._original_prompt = context.scene.mixie_image_to_3d_prompt
        self._original_use_selected = context.scene.mixie_image_to_3d_use_selected
        self._generation_started = False

        return context.window_manager.invoke_popup(self, width=450)

    def check(self, context):
        """Check if generation started - if so, close the popup."""
        if getattr(context.scene, 'mixie_image_to_3d_is_generating', False):
            self._generation_started = True
            return False
        return True

    def cancel(self, context):
        # Only restore values if generation didn't start
        if not self._generation_started:
            if hasattr(self, '_original_prompt'):
                context.scene.mixie_image_to_3d_prompt = self._original_prompt
            if hasattr(self, '_original_use_selected'):
                context.scene.mixie_image_to_3d_use_selected = self._original_use_selected

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="Image to 3D", icon='VIEW3D')
        layout.separator()

        # Prompt with + button for picking input image (like ImageGen)
        row = layout.row(align=True)
        prompt_row = row.row()
        prompt_row.activate_init = True
        prompt_row.prop(scene, "mixie_image_to_3d_prompt", text="")
        row.operator("mixie.image_to_3d_pick_image", text="", icon='ADD')

        layout.separator()

        # Input image section in a box (like ImageGen reference images)
        box = layout.box()
        box_col = box.column(align=True)

        # Checkbox for using selected moodboard image
        row = box_col.row()
        row.prop(scene, "mixie_image_to_3d_use_selected", text="")
        row.label(text="Use Selected Moodboard Image")

        # Show current image info
        if scene.mixie_image_to_3d_use_selected:
            selected = [
                item for item in scene.mixie_moodboard_images
                if item.selected and is_still_item(item)
            ]
            if selected:
                img = selected[0].image
                row = box_col.row()
                row.label(text=f"Selected: {img.name}", icon='CHECKMARK')
            else:
                row = box_col.row()
                row.label(text="No image selected in moodboard", icon='ERROR')
        else:
            # Show uploaded image if any
            if scene.mixie_image_to_3d_image:
                row = box_col.row()
                row.label(text=scene.mixie_image_to_3d_image.name, icon='IMAGE_DATA')

        layout.separator()

        # Model selection with refresh button
        row = layout.row(align=True)
        row.prop(scene, "mixie_image_to_3d_model", text="")
        row.operator("mixie.image_to_3d_refresh_models", text="", icon='FILE_REFRESH')

        layout.separator()

        # Generate button
        row = layout.row()
        row.scale_y = GENERATE_BUTTON_SCALE_Y
        row.operator("mixie.image_to_3d_generate_and_close", text="Generate", icon='PLAY')

    def execute(self, context):
        return {'FINISHED'}


# =============================================================================
# WRAPPER OPERATORS (close popup after starting generation)
# =============================================================================

class MIXIE_OT_mesh_segment_submit_and_close(Operator):
    """Submit mesh segment job and close the popup"""
    bl_idname = "mixie.mesh_segment_submit_and_close"
    bl_label = "Generate"
    bl_description = "Submit mesh segment job and close popup"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        # Check same conditions as the original operator
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            return False
        scene = context.scene
        if not getattr(scene, 'mixie_mesh_segment_description', '').strip():
            return False
        if not getattr(scene, 'mixie_mesh_segment_expected_parts', '').strip():
            return False
        return True

    def execute(self, context):
        # Call the mesh segment submit operator
        bpy.ops.mixie.mesh_segment_submit()
        # Force redraw to trigger popup check
        context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_lookdev_generate_and_close(Operator):
    """Generate lookdev and close the popup"""
    bl_idname = "mixie.lookdev_generate_and_close"
    bl_label = "Generate"
    bl_description = "Generate lookdev and close popup"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return context.space_data and context.space_data.type == 'MIXIE'

    def execute(self, context):
        prompt = context.scene.mixie_lookdev_prompt.strip()
        if not prompt:
            self.report({'WARNING'}, "Please enter a prompt")
            return {'CANCELLED'}

        # Call the lookdev generate operator
        bpy.ops.mixie.lookdev_generate()

        # Clear prompt after submit
        context.scene.mixie_lookdev_prompt = ""

        # Force redraw to trigger popup check
        context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_lookdev360_generate_and_close(Operator):
    """Generate lookdev360 and close the popup"""
    bl_idname = "mixie.lookdev360_generate_and_close"
    bl_label = "Generate"
    bl_description = "Generate lookdev360 and close popup"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return context.space_data and context.space_data.type == 'MIXIE'

    def execute(self, context):
        prompt = context.scene.mixie_lookdev360_prompt.strip()
        if not prompt:
            self.report({'WARNING'}, "Please enter a prompt")
            return {'CANCELLED'}

        # Call the lookdev360 generate operator
        bpy.ops.mixie.lookdev360_generate()

        # Clear prompt after submit
        context.scene.mixie_lookdev360_prompt = ""

        # Force redraw to trigger popup check
        context.area.tag_redraw()
        return {'FINISHED'}


class MIXIE_OT_image_to_3d_generate_and_close(Operator):
    """Generate 3D model and close the popup"""
    bl_idname = "mixie.image_to_3d_generate_and_close"
    bl_label = "Generate"
    bl_description = "Generate 3D model and close popup"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return context.space_data and context.space_data.type == 'MIXIE'

    def execute(self, context):
        # Call the image_to_3d generate operator
        bpy.ops.mixie.image_to_3d_generate()

        # Clear prompt after submit
        context.scene.mixie_image_to_3d_prompt = ""

        # Force redraw to trigger popup check
        context.area.tag_redraw()
        return {'FINISHED'}


# Only include classes if MIXIE space is available
classes = (
    MIXIE_OT_mesh_segment_popup,
    MIXIE_OT_lookdev_popup,
    MIXIE_OT_lookdev360_popup,
    MIXIE_OT_image_to_3d_popup,
    MIXIE_OT_mesh_segment_submit_and_close,
    MIXIE_OT_lookdev_generate_and_close,
    MIXIE_OT_lookdev360_generate_and_close,
    MIXIE_OT_image_to_3d_generate_and_close,
) if MIXIE_SPACE_AVAILABLE else ()
