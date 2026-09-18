# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Space Panels

Panel definitions for the Mixie space sidebar.
Panels are controlled via scene.mixie_active_panel property.
"""

import bpy
from bpy.types import Panel

from ..constants import get_imagegen_max_refs


class MIXIE_PT_mesh_segment(Panel):
    """UV Mesh Segmentation panel"""
    bl_label = "Mesh Segment"
    bl_idname = "MIXIE_PT_mesh_segment"
    bl_space_type = 'MIXIE'
    bl_region_type = 'UI'
    bl_category = "Mixie"

    @classmethod
    def poll(cls, context):
        # Check enum property for MESH_SEGMENT panel visibility
        return context.scene.mixie_active_panel == 'MESH_SEGMENT'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="UV Mesh Segmentation", icon='UV_DATA')
        layout.separator()

        # Object Selection Info
        box = layout.box()
        box.label(text="Selected Mesh", icon='OBJECT_DATA')

        obj = context.active_object
        if obj and obj.type == 'MESH':
            box.label(text=f"Object: {obj.name}", icon='CHECKMARK')
            # Check for UV map
            if obj.data.uv_layers:
                box.label(text=f"UV Maps: {len(obj.data.uv_layers)}", icon='UV')
            else:
                row = box.row()
                row.alert = True
                row.label(text="No UV map! Please unwrap first.", icon='ERROR')
        else:
            box.label(text="No mesh object selected", icon='ERROR')

        # Input Parameters
        layout.separator()
        box = layout.box()
        box.label(text="Mesh Segment Parameters", icon='SETTINGS')

        box.label(text="Description:")
        box.prop(scene, "mixie_mesh_segment_description", text="")

        box.label(text="Expected Parts (comma-separated):")
        box.prop(scene, "mixie_mesh_segment_expected_parts", text="")

        # Error Message (if any)
        if scene.mixie_mesh_segment_error:
            layout.separator()
            error_box = layout.box()
            error_box.alert = True
            error_row = error_box.row()
            error_row.label(text="Error:", icon='ERROR')
            error_text = scene.mixie_mesh_segment_error
            if len(error_text) > 50:
                error_box.label(text=error_text[:50] + "...")
            else:
                error_box.label(text=error_text)

        # Progress display (when processing)
        if scene.mixie_mesh_segment_is_processing:
            layout.separator()
            box = layout.box()
            box.label(text="Processing...", icon='SORTTIME')

            # Progress bar with percentage
            progress_pct = int(scene.mixie_mesh_segment_progress * 100)
            row = box.row()
            row.progress(factor=scene.mixie_mesh_segment_progress, text=f"Progress: {progress_pct}%")

            if scene.mixie_mesh_segment_current_step:
                box.label(text=f"Step: {scene.mixie_mesh_segment_current_step}")

            # Cancel button
            row = box.row()
            row.scale_y = 1.2
            row.operator("mixie.mesh_segment_cancel", text="Cancel", icon='CANCEL')

        else:
            # Submit button
            layout.separator()
            row = layout.row()
            row.scale_y = 1.5

            can_submit = (
                obj is not None and
                obj.type == 'MESH' and
                scene.mixie_mesh_segment_description.strip() and
                scene.mixie_mesh_segment_expected_parts.strip()
            )

            if not can_submit:
                row.enabled = False
                if not obj or obj.type != 'MESH':
                    row.operator("mixie.mesh_segment_submit", text="Select a Mesh", icon='ERROR')
                elif not scene.mixie_mesh_segment_description.strip():
                    row.operator("mixie.mesh_segment_submit", text="Enter Description", icon='ERROR')
                else:
                    row.operator("mixie.mesh_segment_submit", text="Enter Expected Parts", icon='ERROR')
            else:
                row.operator("mixie.mesh_segment_submit", text="Submit Mesh Segment", icon='PLAY')

        # Result display (when completed)
        if scene.mixie_mesh_segment_status == "completed" and scene.mixie_mesh_segment_result:
            layout.separator()
            box = layout.box()
            box.label(text="Result", icon='CHECKMARK')
            box.label(text="Labels applied as vertex groups")
            box.label(text=f"Status: {scene.mixie_mesh_segment_status}")


class MIXIE_PT_lookdev(Panel):
    """Lookdev mode panel for generating images from depth maps"""
    bl_label = "Lookdev"
    bl_idname = "MIXIE_PT_lookdev"
    bl_space_type = 'MIXIE'
    bl_region_type = 'UI'
    bl_category = "Mixie"

    @classmethod
    def poll(cls, context):
        # Check enum property for LOOKDEV panel visibility
        return context.scene.mixie_active_panel == 'LOOKDEV'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="Lookdev Generation", icon='RENDER_RESULT')
        layout.separator()

        # Depth Map Selection
        box = layout.box()
        box.label(text="Depth Map Source", icon='IMAGE_DATA')

        box.prop(scene, "mixie_lookdev_use_selected", text="Use Selected Moodboard Image")

        if not scene.mixie_lookdev_use_selected:
            # File picker mode
            row = box.row(align=True)
            if scene.mixie_lookdev_depth_image:
                row.prop(scene, "mixie_lookdev_depth_image", text="")
            else:
                row.label(text="No depth map selected")
            row.operator("mixie.lookdev_pick_depth_image", text="", icon='FILEBROWSER')
        else:
            # Show currently selected moodboard image info
            selected = [
                item for item in scene.mixie_moodboard_images
                if item.selected and item.image
            ]
            if selected:
                img = selected[0].image
                box.label(text=f"Selected: {img.name}", icon='CHECKMARK')
            else:
                box.label(text="No image selected in moodboard", icon='ERROR')

        # Prompt Input
        layout.separator()
        box = layout.box()
        box.label(text="Generation Settings", icon='TEXT')
        box.prop(scene, "mixie_lookdev_prompt", text="Prompt")

        # Error Message (if any)
        if scene.mixie_lookdev_error:
            layout.separator()
            error_box = layout.box()
            error_box.alert = True
            error_row = error_box.row()
            error_row.label(text="Error:", icon='ERROR')
            # Split long error messages
            error_text = scene.mixie_lookdev_error
            if len(error_text) > 50:
                error_box.label(text=error_text[:50] + "...")
                error_box.label(text="..." + error_text[50:100] if len(error_text) > 50 else "")
            else:
                error_box.label(text=error_text)

        # Generate from Scene Button (renders depth from 3D viewport)
        layout.separator()
        box = layout.box()
        box.label(text="Generate from 3D Scene", icon='VIEW3D')
        row = box.row()
        row.scale_y = 1.5

        if scene.mixie_lookdev_is_generating:
            row.enabled = False
            row.operator("mixie.lookdev_generate_from_scene", text="Generating...", icon='SORTTIME')
        else:
            row.operator("mixie.lookdev_generate_from_scene", text="Generate from Scene", icon='SCENE_DATA')

        # Generate from Image Button (uses selected/picked depth map)
        layout.separator()
        row = layout.row()
        row.scale_y = 1.5

        if scene.mixie_lookdev_is_generating:
            row.enabled = False
            row.operator("mixie.lookdev_generate", text="Generating...", icon='SORTTIME')
        else:
            row.operator("mixie.lookdev_generate", text="Generate from Image", icon='IMAGE_DATA')


class MIXIE_PT_lookdev360(Panel):
    """Lookdev 360 panel for generating textures from 3D objects"""
    bl_label = "Lookdev 360"
    bl_idname = "MIXIE_PT_lookdev360"
    bl_space_type = 'MIXIE'
    bl_region_type = 'UI'
    bl_category = "Mixie"

    @classmethod
    def poll(cls, context):
        # Check enum property for LOOKDEV360 panel visibility
        return context.scene.mixie_active_panel == 'LOOKDEV360'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="Lookdev 360 Texturing", icon='FILE_3D')
        layout.separator()

        # Object Selection Info
        box = layout.box()
        box.label(text="Object Selection", icon='OBJECT_DATA')

        # Count selected mesh objects
        mesh_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        mesh_count = len(mesh_objects)

        if mesh_count == 0:
            box.label(text="No mesh objects selected", icon='ERROR')
        else:
            box.label(text=f"{mesh_count} mesh object(s) selected", icon='CHECKMARK')

            # Check for objects without UV maps
            objects_without_uv = 0
            for obj in mesh_objects:
                if obj.data and (not obj.data.uv_layers or len(obj.data.uv_layers) == 0):
                    objects_without_uv += 1

            if objects_without_uv > 0:
                row = box.row()
                row.alert = True
                row.label(text=f"{objects_without_uv} object(s) missing UV map", icon='INFO')
                row = box.row()
                row.label(text="(Will be auto-unwrapped)", icon='BLANK1')

        # Style Reference Section
        layout.separator()
        box = layout.box()
        box.label(text="Style Reference", icon='IMAGE_DATA')

        box.prop(scene, "mixie_lookdev360_use_selected_image", text="Use Selected Moodboard Image")

        if scene.mixie_lookdev360_use_selected_image:
            # Show currently selected moodboard image info
            selected = [
                item for item in scene.mixie_moodboard_images
                if item.selected and item.image
            ]
            if selected:
                img = selected[0].image
                box.label(text=f"Selected: {img.name}", icon='CHECKMARK')
            else:
                box.label(text="No image selected in moodboard", icon='INFO')
        else:
            # File picker mode
            row = box.row(align=True)
            if scene.mixie_lookdev360_style_image:
                row.prop(scene, "mixie_lookdev360_style_image", text="")
            else:
                row.label(text="No style image selected")
            row.operator("mixie.lookdev360_pick_style_image", text="", icon='FILEBROWSER')

        # Prompt Input
        layout.separator()
        box = layout.box()
        box.label(text="Generation Settings", icon='TEXT')
        box.prop(scene, "mixie_lookdev360_prompt", text="Prompt")

        # Error Message (if any)
        if scene.mixie_lookdev360_error:
            layout.separator()
            error_box = layout.box()
            error_box.alert = True
            error_row = error_box.row()
            error_row.label(text="Error:", icon='ERROR')
            # Split long error messages
            error_text = scene.mixie_lookdev360_error
            if len(error_text) > 50:
                error_box.label(text=error_text[:50] + "...")
                error_box.label(text="..." + error_text[50:100] if len(error_text) > 50 else "")
            else:
                error_box.label(text=error_text)

        # Generate Button
        layout.separator()
        row = layout.row()
        row.scale_y = 1.5

        # Disable if no mesh objects selected or generating
        can_generate = mesh_count > 0 and not scene.mixie_lookdev360_is_generating

        if scene.mixie_lookdev360_is_generating:
            row.enabled = False
            row.operator("mixie.lookdev360_generate", text="Generating...", icon='SORTTIME')
        elif mesh_count == 0:
            row.enabled = False
            row.operator("mixie.lookdev360_generate", text="Select Objects First", icon='ERROR')
        else:
            row.operator("mixie.lookdev360_generate", text="Generate Textures", icon='MATERIAL')

        # Restore Button (visible only after materials applied)
        if scene.mixie_lookdev360_has_applied:
            layout.separator()
            box = layout.box()
            box.label(text="Undo", icon='LOOP_BACK')
            row = box.row()
            row.scale_y = 1.2
            row.operator("mixie.lookdev360_restore", text="Restore Original Materials", icon='FILE_REFRESH')


class MIXIE_PT_imagegen(Panel):
    """Image Gen panel for AI image generation"""
    bl_label = "Image Gen"
    bl_idname = "MIXIE_PT_imagegen"
    bl_space_type = 'MIXIE'
    bl_region_type = 'UI'
    bl_category = "Mixie"

    @classmethod
    def poll(cls, context):
        # Check enum property for IMAGEGEN panel visibility
        return context.scene.mixie_active_panel == 'IMAGEGEN'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="AI Image Generation", icon='IMAGE')
        layout.separator()

        # Reference Images Section
        box = layout.box()
        box.label(text="Reference Images", icon='IMAGE_REFERENCE')

        # Add reference images button
        row = box.row(align=True)
        row.operator("mixie.imagegen_add_style_image", text="Add Style Image", icon='IMAGE_DATA')
        if len(scene.mixie_imagegen_ref_images) > 0:
            op = row.operator("mixie.imagegen_remove_style_image", text="", icon='X')
            op.index = -1  # Clear all

        # Show added reference images
        for i, ref_item in enumerate(scene.mixie_imagegen_ref_images):
            if ref_item.image:
                row = box.row()
                if ref_item.image.preview:
                    row.template_icon(icon_value=ref_item.image.preview.icon_id, scale=3.0)
                row.label(text=ref_item.image.name)
                op = row.operator("mixie.imagegen_remove_style_image", text="", icon='X')
                op.index = i

        # Show selected moodboard images as reference
        ref_count = sum(1 for img in scene.mixie_moodboard_images if img.selected and img.image)
        added_ref_count = len(scene.mixie_imagegen_ref_images)
        total_ref = ref_count + added_ref_count
        max_refs = get_imagegen_max_refs(scene.mixie_imagegen_model)
        max_moodboard = max_refs - added_ref_count  # Remaining slots after added images

        if ref_count > 0 or added_ref_count > 0:
            row = box.row()
            if total_ref > max_refs:
                row.alert = True
                row.label(text=f"{total_ref} total (max {max_refs} for {scene.mixie_imagegen_model.capitalize()})", icon='ERROR')
            else:
                if ref_count > max_moodboard:
                    row.alert = True
                    row.label(text=f"{ref_count} selected (only {max_moodboard} will be used)", icon='INFO')
                else:
                    row.label(text=f"{total_ref} reference image(s)", icon='CHECKMARK')

        # Generation Settings Section
        layout.separator()
        box = layout.box()
        box.label(text="Generation Settings", icon='SETTINGS')

        box.label(text="Prompt:")
        box.prop(scene, "mixie_imagegen_prompt", text="")

        box.label(text="Negative Prompt (optional):")
        box.prop(scene, "mixie_imagegen_negative_prompt", text="")

        row = box.row(align=True)
        row.prop(scene, "mixie_imagegen_style", text="")
        row.prop(scene, "mixie_imagegen_model", text="")
        row.prop(scene, "mixie_imagegen_aspect_ratio", text="")

        # Error Message (if any)
        if scene.mixie_imagegen_error:
            layout.separator()
            error_box = layout.box()
            error_box.alert = True
            error_row = error_box.row()
            error_row.label(text="Error:", icon='ERROR')
            error_text = scene.mixie_imagegen_error
            if len(error_text) > 50:
                error_box.label(text=error_text[:50] + "...")
                error_box.label(text="..." + error_text[50:100] if len(error_text) > 50 else "")
            else:
                error_box.label(text=error_text)

        # Generate Button
        layout.separator()
        row = layout.row()
        row.scale_y = 1.5

        if scene.mixie_imagegen_is_generating:
            row.enabled = False
            row.operator("mixie.imagegen_generate", text="Generating...", icon='SORTTIME')
        else:
            row.operator("mixie.imagegen_generate", text="Generate Image", icon='SHADERFX')


class MIXIE_PT_image_to_3d(Panel):
    """Image to 3D panel for generating 3D models from images"""
    bl_label = "Image to 3D"
    bl_idname = "MIXIE_PT_image_to_3d"
    bl_space_type = 'MIXIE'
    bl_region_type = 'UI'
    bl_category = "Mixie"

    @classmethod
    def poll(cls, context):
        # Check enum property for IMAGE_TO_3D panel visibility
        return context.scene.mixie_active_panel == 'IMAGE_TO_3D'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="Image to 3D Generation", icon='MESH_CUBE')
        layout.separator()

        # Input Image Section
        box = layout.box()
        box.label(text="Input Image", icon='IMAGE_DATA')

        box.prop(scene, "mixie_image_to_3d_use_selected", text="Use Selected Moodboard Image")

        if scene.mixie_image_to_3d_use_selected:
            # Show currently selected moodboard image info
            selected = [
                item for item in scene.mixie_moodboard_images
                if item.selected and item.image
            ]
            if selected:
                img = selected[0].image
                box.label(text=f"Selected: {img.name}", icon='CHECKMARK')
            else:
                box.label(text="No image selected in moodboard", icon='ERROR')
        else:
            # File picker mode
            row = box.row(align=True)
            if scene.mixie_image_to_3d_image:
                row.prop(scene, "mixie_image_to_3d_image", text="")
            else:
                row.label(text="No image selected")
            row.operator("mixie.image_to_3d_pick_image", text="", icon='FILEBROWSER')

        # Prompt Input (Optional)
        layout.separator()
        box = layout.box()
        box.label(text="Prompt (Optional)", icon='TEXT')
        box.prop(scene, "mixie_image_to_3d_prompt", text="")

        # Model Selection
        layout.separator()
        box = layout.box()
        box.label(text="Model Selection", icon='SETTINGS')
        box.prop(scene, "mixie_image_to_3d_model", text="")

        # Dynamic Parameters based on model selection
        layout.separator()
        if scene.mixie_image_to_3d_model == 'TRELLIS_1':
            self._draw_trellis_1_params(layout, scene)
        else:
            self._draw_trellis_2_params(layout, scene)

        # Error Message (if any)
        if scene.mixie_image_to_3d_error:
            layout.separator()
            error_box = layout.box()
            error_box.alert = True
            error_row = error_box.row()
            error_row.label(text="Error:", icon='ERROR')
            error_text = scene.mixie_image_to_3d_error
            if len(error_text) > 50:
                error_box.label(text=error_text[:50] + "...")
                error_box.label(text="..." + error_text[50:100] if len(error_text) > 50 else "")
            else:
                error_box.label(text=error_text)

        # Generate Button
        layout.separator()
        row = layout.row()
        row.scale_y = 1.5

        # Check if we have an image to generate from
        has_image = False
        if scene.mixie_image_to_3d_use_selected:
            selected = [item for item in scene.mixie_moodboard_images if item.selected and item.image]
            has_image = len(selected) > 0
        else:
            has_image = scene.mixie_image_to_3d_image is not None

        if scene.mixie_image_to_3d_is_generating:
            row.enabled = False
            row.operator("mixie.image_to_3d_generate", text="Generating...", icon='SORTTIME')
        elif not has_image:
            row.enabled = False
            row.operator("mixie.image_to_3d_generate", text="Select Image First", icon='ERROR')
        else:
            row.operator("mixie.image_to_3d_generate", text="Generate 3D Model", icon='MESH_CUBE')

    def _draw_trellis_1_params(self, layout, scene):
        """Draw Trellis 1.0 specific parameters."""
        box = layout.box()
        box.label(text="Trellis 1.0 Parameters", icon='MODIFIER')

        col = box.column(align=True)
        col.prop(scene, "mixie_image_to_3d_t1_seed")
        col.prop(scene, "mixie_image_to_3d_t1_texture_size")
        col.prop(scene, "mixie_image_to_3d_t1_mesh_simplify")

        col.separator()
        col.prop(scene, "mixie_image_to_3d_t1_randomize_seed")
        col.prop(scene, "mixie_image_to_3d_t1_generate_color")
        col.prop(scene, "mixie_image_to_3d_t1_generate_model")
        col.prop(scene, "mixie_image_to_3d_t1_generate_normal")
        col.prop(scene, "mixie_image_to_3d_t1_save_gaussian_ply")
        col.prop(scene, "mixie_image_to_3d_t1_return_no_background")

        # Advanced parameters in sub-box
        adv_box = box.box()
        adv_box.label(text="Advanced", icon='PREFERENCES')
        adv_col = adv_box.column(align=True)
        adv_col.prop(scene, "mixie_image_to_3d_t1_ss_sampling_steps")
        adv_col.prop(scene, "mixie_image_to_3d_t1_slat_sampling_steps")
        adv_col.prop(scene, "mixie_image_to_3d_t1_ss_guidance_strength")
        adv_col.prop(scene, "mixie_image_to_3d_t1_slat_guidance_strength")

    def _draw_trellis_2_params(self, layout, scene):
        """Draw Trellis 2.0 specific parameters."""
        box = layout.box()
        box.label(text="Trellis 2.0 Parameters", icon='MODIFIER')

        col = box.column(align=True)
        col.prop(scene, "mixie_image_to_3d_t2_seed")
        col.prop(scene, "mixie_image_to_3d_t2_texture_size")
        col.prop(scene, "mixie_image_to_3d_t2_decimation_target")
        col.prop(scene, "mixie_image_to_3d_t2_pipeline_type")

        col.separator()
        col.prop(scene, "mixie_image_to_3d_t2_randomize_seed")
        col.prop(scene, "mixie_image_to_3d_t2_generate_model")
        col.prop(scene, "mixie_image_to_3d_t2_generate_video")
        col.prop(scene, "mixie_image_to_3d_t2_preprocess_image")
        col.prop(scene, "mixie_image_to_3d_t2_return_no_background")

        # Shape SLAT parameters
        shape_box = box.box()
        shape_box.label(text="Shape SLAT", icon='MESH_DATA')
        shape_col = shape_box.column(align=True)
        shape_col.prop(scene, "mixie_image_to_3d_t2_shape_slat_steps")
        shape_col.prop(scene, "mixie_image_to_3d_t2_shape_slat_guidance_strength")
        shape_col.prop(scene, "mixie_image_to_3d_t2_shape_slat_guidance_rescale")
        shape_col.prop(scene, "mixie_image_to_3d_t2_shape_slat_rescale_t")

        # Sparse Structure parameters
        sparse_box = box.box()
        sparse_box.label(text="Sparse Structure", icon='OUTLINER_OB_POINTCLOUD')
        sparse_col = sparse_box.column(align=True)
        sparse_col.prop(scene, "mixie_image_to_3d_t2_sparse_structure_steps")
        sparse_col.prop(scene, "mixie_image_to_3d_t2_sparse_structure_guidance_strength")
        sparse_col.prop(scene, "mixie_image_to_3d_t2_sparse_structure_guidance_rescale")
        sparse_col.prop(scene, "mixie_image_to_3d_t2_sparse_structure_rescale_t")

        # Texture SLAT parameters
        tex_box = box.box()
        tex_box.label(text="Texture SLAT", icon='TEXTURE')
        tex_col = tex_box.column(align=True)
        tex_col.prop(scene, "mixie_image_to_3d_t2_tex_slat_steps")
        tex_col.prop(scene, "mixie_image_to_3d_t2_tex_slat_guidance_strength")
        tex_col.prop(scene, "mixie_image_to_3d_t2_tex_slat_guidance_rescale")
        tex_col.prop(scene, "mixie_image_to_3d_t2_tex_slat_rescale_t")


# Panels disabled - functionality moved to pie menu popups in moodboard/ui/operators/generative_popup_ops.py
# To re-enable, uncomment the classes tuple below
# classes = (
#     MIXIE_PT_mesh_segment,
#     MIXIE_PT_lookdev,
#     MIXIE_PT_lookdev360,
#     MIXIE_PT_imagegen,
#     MIXIE_PT_image_to_3d,
# )
classes = ()
