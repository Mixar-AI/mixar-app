# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Scene Popup Operators

Popup dialogs for Segment to 3D and Scene Reconstruction features.
"""

import bpy
from bpy.types import Operator

from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE
from mixar.modules.moodboard.constants import GENERATE_BUTTON_SCALE_Y


# =============================================================================
# SEGMENT TO 3D POPUP
# =============================================================================

class MIXIE_OT_segment_to_3d_popup(Operator):
    """Open Segment to 3D popup dialog"""
    bl_idname = "mixie.segment_to_3d_popup"
    bl_label = "Segment to 3D"
    bl_description = "Open segment to 3D dialog for image segmentation and scene generation"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        if not context.space_data or context.space_data.type != 'MIXIE':
            return False
        # Require at least one image selected
        scene = context.scene
        if hasattr(scene, 'mixie_moodboard_images'):
            for img_item in scene.mixie_moodboard_images:
                if img_item.selected and img_item.image:
                    return True
        return False

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=450)

    def _get_selected_image(self, context):
        """Get the first selected image and its index"""
        scene = context.scene
        if hasattr(scene, 'mixie_moodboard_images'):
            for i, img_item in enumerate(scene.mixie_moodboard_images):
                if img_item.selected and img_item.image:
                    return i, img_item
        return -1, None

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        state = scene.mixie_edit_tool_state

        layout.label(text="Segment to 3D", icon='MOD_MASK')
        layout.separator()

        # Find selected image
        selected_idx, selected_item = self._get_selected_image(context)

        if selected_idx < 0 or not selected_item:
            layout.label(text="No image selected", icon='INFO')
            return

        # Show image name
        box = layout.box()
        box.label(text=selected_item.image.name, icon='IMAGE_DATA')

        # Box Select SAM button
        if state.box_select_has_selection or state.box_select_pending:
            sam_box = layout.box()
            sam_box.label(text="Box Selection:", icon='SELECT_SET')

            if state.box_select_pending:
                row = sam_box.row()
                row.enabled = False
                row.operator("mixie.box_select_sam", text="Processing...", icon='SORTTIME')
            else:
                row = sam_box.row()
                row.scale_y = 1.3
                row.operator("mixie.box_select_sam", text="Identify and select", icon='MOD_MASK')

        # Lasso Select SAM button
        if state.lasso_select_has_selection or state.lasso_select_pending:
            sam_box = layout.box()
            sam_box.label(text="Multi-Lasso Selection:", icon='OUTLINER_DATA_GP_LAYER')

            if state.lasso_select_pending:
                row = sam_box.row()
                row.enabled = False
                row.operator("mixie.lasso_select_sam", text="Refining...", icon='SORTTIME')
            else:
                row = sam_box.row()
                row.scale_y = 1.3
                row.operator(
                    "mixie.lasso_select_sam",
                    text="Finish & Refine with SAM3",
                    icon='MOD_MASK',
                )

        # Show segment count
        num_segments = len(selected_item.segments)
        if num_segments == 0:
            layout.separator()
            layout.label(text="No segments yet", icon='INFO')
            layout.label(text="Use selection tools to create segments")
            return

        layout.separator()

        # List segments
        layout.label(text=f"Segments ({num_segments}):")

        for i, segment in enumerate(selected_item.segments):
            row = layout.row(align=True)

            # Toggle checkbox
            icon = 'CHECKBOX_HLT' if segment.active else 'CHECKBOX_DEHLT'
            op = row.operator("mixie.toggle_segment", text="", icon=icon, emboss=False)
            op.image_index = selected_idx
            op.segment_index = i

            # Segment name
            row.label(text=segment.name)

            # Delete button
            op = row.operator("mixie.delete_segment", text="", icon='X')
            op.image_index = selected_idx
            op.segment_index = i

        # Status info
        active_count = sum(1 for s in selected_item.segments if s.active)
        if active_count > 0:
            layout.separator()
            layout.label(text=f"{active_count} segment(s) active", icon='CHECKMARK')

        # Generate Scene button
        layout.separator()
        row = layout.row()
        row.scale_y = 1.5
        row.operator("mixie.generate_scene", text="Generate Scene", icon='SCENE_DATA')

    def execute(self, context):
        return {'FINISHED'}


# =============================================================================
# SCENE RECON POPUP
# =============================================================================

class MIXIE_OT_scene_recon_popup(Operator):
    """Open Scene Reconstruction popup dialog"""
    bl_idname = "mixie.scene_recon_popup"
    bl_label = "Generate Scene"
    bl_description = "Open scene reconstruction dialog"
    bl_options = {'REGISTER'}

    _generation_started: bool = False

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return context.space_data and context.space_data.type == 'MIXIE'

    def invoke(self, context, event):
        sidebar = context.scene.mixie_moodboard_sidebar
        tab = sidebar.tab_scene_recon
        self._original_prompt = tab.prompt
        self._original_use_selected = tab.use_selected_image
        self._original_generate_mesh = tab.generate_mesh
        self._generation_started = False
        return context.window_manager.invoke_popup(self, width=450)

    def check(self, context):
        if getattr(context.scene, 'mixie_scene_recon_is_generating', False):
            self._generation_started = True
            return False
        return True

    def cancel(self, context):
        if not self._generation_started:
            sidebar = context.scene.mixie_moodboard_sidebar
            tab = sidebar.tab_scene_recon
            if hasattr(self, '_original_prompt'):
                tab.prompt = self._original_prompt
            if hasattr(self, '_original_use_selected'):
                tab.use_selected_image = self._original_use_selected
            if hasattr(self, '_original_generate_mesh'):
                tab.generate_mesh = self._original_generate_mesh

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        sidebar = scene.mixie_moodboard_sidebar
        tab = sidebar.tab_scene_recon

        layout.label(text="Scene Reconstruction", icon='SCENE_DATA')
        layout.separator()

        # Prompt input
        row = layout.row()
        row.activate_init = True
        row.prop(tab, "prompt", text="")

        layout.separator()

        # Image input section
        box = layout.box()
        box_col = box.column(align=True)

        # Toggle: use selected moodboard image
        row = box_col.row()
        row.prop(tab, "use_selected_image", text="")
        row.label(text="Use Selected Moodboard Image")

        if tab.use_selected_image:
            selected = [
                item for item in scene.mixie_moodboard_images
                if item.selected and item.image
            ]
            if selected:
                row = box_col.row()
                row.label(text=f"Selected: {selected[0].image.name}", icon='CHECKMARK')
            else:
                row = box_col.row()
                row.label(text="No image selected in moodboard", icon='ERROR')
        else:
            # File picker
            if tab.image_name:
                row = box_col.row(align=True)
                row.label(text=tab.image_name, icon='IMAGE_DATA')
                row.operator("mixie.scene_recon_remove_image", text="", icon='X')
            else:
                box_col.operator("mixie.scene_recon_pick_image", text="Pick Image", icon='ADD')

        layout.separator()

        # Pipeline options
        settings_box = layout.box()
        settings_col = settings_box.column(align=True)
        settings_col.prop(tab, "generate_mesh")
        settings_col.prop(tab, "mesh_postprocess")
        settings_col.prop(tab, "vertex_color")
        settings_col.prop(tab, "min_mask_pixels")

        layout.separator()
        row = layout.row()
        row.scale_y = GENERATE_BUTTON_SCALE_Y
        row.operator(
            "mixie.scene_recon_generate_and_close",
            text="Reconstruct", icon='PLAY'
        )

    def execute(self, context):
        return {'FINISHED'}


# =============================================================================
# SCENE RECON GENERATE AND CLOSE
# =============================================================================

class MIXIE_OT_scene_recon_generate_and_close(Operator):
    """Generate scene reconstruction and close the popup"""
    bl_idname = "mixie.scene_recon_generate_and_close"
    bl_label = "Reconstruct"
    bl_description = "Start scene reconstruction and close popup"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        return context.space_data and context.space_data.type == 'MIXIE'

    def execute(self, context):
        bpy.ops.mixie.scene_recon_generate()
        context.area.tag_redraw()
        return {'FINISHED'}


# Only include classes if MIXIE space is available
classes = (
    MIXIE_OT_segment_to_3d_popup,
    MIXIE_OT_scene_recon_popup,
    MIXIE_OT_scene_recon_generate_and_close,
) if MIXIE_SPACE_AVAILABLE else ()
