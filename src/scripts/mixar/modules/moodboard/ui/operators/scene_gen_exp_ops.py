# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Gen Experimental Operators.

Pick / remove image and submit to the backend labels endpoint.
"""

import os

import bpy
from bpy.types import Operator
from mixar.modules.moodboard.core.media_utils import is_still_item

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.image_utils import compress_image_for_upload
from ....common.utils.file_select_utils import file_select_guard, mark_file_select_executed
from ...core.image_lifecycle import remove_image_safely

logger = get_logger(__name__)


def _get_tab(context):
    scene = context.scene
    if not hasattr(scene, 'mixie_moodboard_sidebar'):
        return None
    sidebar = scene.mixie_moodboard_sidebar
    if not hasattr(sidebar, 'tab_scene_gen_exp'):
        return None
    return sidebar.tab_scene_gen_exp


class MIXIE_OT_scene_gen_exp_pick_image(Operator):
    """Select an image file for label extraction"""

    bl_idname = "mixie.scene_gen_exp_pick_image"
    bl_label = "Pick Image"
    bl_description = "Select an image file for label extraction"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to the input image file",
        subtype="FILE_PATH",
    )

    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.webp", options={"HIDDEN"}
    )

    def invoke(self, context, event):
        if not file_select_guard(self, context):
            return {"FINISHED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.filepath:
            self.report({"WARNING"}, "No file selected")
            return {"CANCELLED"}

        try:
            filepath = os.path.abspath(os.path.realpath(self.filepath))
        except (OSError, ValueError) as e:
            self.report({"ERROR"}, f"Invalid file path: {e}")
            return {"CANCELLED"}

        if not os.path.isfile(filepath):
            self.report({"ERROR"}, f"File not found: {filepath}")
            return {"CANCELLED"}

        valid_extensions = {'.png', '.jpg', '.jpeg', '.webp'}
        file_ext = os.path.splitext(filepath)[1].lower()
        if file_ext not in valid_extensions:
            self.report({"ERROR"}, f"Invalid image format: {file_ext}")
            return {"CANCELLED"}

        try:
            img = bpy.data.images.load(filepath, check_existing=True)
            img.pack()
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {e}")
            return {"CANCELLED"}

        tab = _get_tab(context)
        if tab is None:
            self.report({"ERROR"}, "Sidebar properties not found")
            return {"CANCELLED"}

        tab.reference_image = img
        self.report({"INFO"}, f"Selected '{img.name}'")
        mark_file_select_executed(self)
        return {"FINISHED"}


class MIXIE_OT_scene_gen_exp_remove_image(Operator):
    """Remove the input image from Scene Gen Experimental tab"""

    bl_idname = "mixie.scene_gen_exp_remove_image"
    bl_label = "Remove Image"
    bl_description = "Remove the input image"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tab = _get_tab(context)
        if tab is None:
            self.report({"ERROR"}, "Sidebar properties not found")
            return {"CANCELLED"}
        old_img = getattr(tab, 'reference_image', None)
        tab.reference_image = None
        remove_image_safely(old_img)
        self.report({"INFO"}, "Input image removed")
        return {"FINISHED"}


class MIXIE_OT_scene_gen_exp_toggle_all(Operator):
    """Toggle all labels selected/deselected"""

    bl_idname = "mixie.scene_gen_exp_toggle_all"
    bl_label = "Toggle All"
    bl_description = "Toggle all labels selected or deselected"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tab = _get_tab(context)
        if tab is None:
            self.report({"ERROR"}, "Sidebar properties not found")
            return {"CANCELLED"}

        # If any are selected, deselect all; otherwise select all
        any_selected = any(obj.selected for obj in tab.objects)
        new_state = not any_selected
        for obj in tab.objects:
            obj.selected = new_state
        return {"FINISHED"}


class MIXIE_OT_scene_gen_exp_generate_images(Operator):
    """Generate one image per selected detected object (Step 2)"""

    bl_idname = "mixie.scene_gen_exp_generate_images"
    bl_label = "Generate Images"
    bl_description = (
        "Fire one image generation request per selected object, using the "
        "current Step 1 input image as reference"
    )
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        tab = _get_tab(context)
        if tab is None:
            self.report({"ERROR"}, "Sidebar properties not found")
            return {"CANCELLED"}

        selected_count = sum(1 for obj in tab.objects if obj.selected)
        if selected_count == 0:
            self.report({"WARNING"}, "Select at least one object")
            return {"CANCELLED"}

        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        tab = _get_tab(context)
        if tab is None:
            self.report({"ERROR"}, "Sidebar properties not found")
            return {"CANCELLED"}

        if not tab.has_result or len(tab.objects) == 0:
            self.report({"WARNING"}, "Run Step 1 (Extract labels) first")
            return {"CANCELLED"}

        if tab.gen_in_progress:
            self.report({"WARNING"}, "Image generation already in progress")
            return {"CANCELLED"}

        if getattr(scene, 'mixie_scene_gen_exp_is_processing', False):
            self.report({"WARNING"}, "Step 1 is still running")
            return {"CANCELLED"}

        selected_count = sum(1 for obj in tab.objects if obj.selected)
        if selected_count == 0:
            self.report({"WARNING"}, "Select at least one object")
            return {"CANCELLED"}

        # Recompute the reference image from current use_selected_image toggle
        # so the user sees the exact same source behavior as Step 1.
        image_bytes = None
        use_selected = getattr(tab, 'use_selected_image', True)
        if use_selected:
            selected_mb = [
                item for item in scene.mixie_moodboard_images
                if item.selected and is_still_item(item)
            ]
            if not selected_mb:
                self.report({"WARNING"}, "Please select an image in the moodboard")
                return {"CANCELLED"}
            try:
                image_bytes = compress_image_for_upload(selected_mb[0].image)
            except Exception as e:
                self.report({"ERROR"}, f"Failed to process image: {e}")
                return {"CANCELLED"}
        else:
            if not tab.reference_image:
                self.report({"WARNING"}, "Please select or upload an image")
                return {"CANCELLED"}
            try:
                image_bytes = compress_image_for_upload(tab.reference_image)
            except Exception as e:
                self.report({"ERROR"}, f"Failed to process image: {e}")
                return {"CANCELLED"}

        try:
            from mixar.modules.moodboard.core.scene_gen_exp_manager import (
                get_scene_gen_exp_manager,
            )
        except ImportError as e:
            self.report({"ERROR"}, f"Scene gen exp manager not available: {e}")
            return {"CANCELLED"}

        manager = get_scene_gen_exp_manager()
        success, message = manager.generate_object_images(
            image_bytes=image_bytes,
            model=tab.imagegen_model,
            aspect_ratio=tab.imagegen_aspect_ratio,
            resolution=tab.imagegen_resolution,
        )

        if not success:
            self.report({"WARNING"}, message or "Failed to start image generation")
            return {"CANCELLED"}

        # Lock label renaming once Step 2 starts
        tab.rename_allowed = False

        self.report({"INFO"}, f"Generating {selected_count} image(s)...")
        return {"FINISHED"}


class MIXIE_OT_scene_gen_exp_clear(Operator):
    """Clear all Scene Gen Experimental results and reset state"""

    bl_idname = "mixie.scene_gen_exp_clear"
    bl_label = "Clear"
    bl_description = "Clear extracted labels and image generation results"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tab = _get_tab(context)
        if tab is None:
            self.report({"ERROR"}, "Sidebar properties not found")
            return {"CANCELLED"}

        scene = context.scene

        # Don't clear while processing
        if getattr(scene, 'mixie_scene_gen_exp_is_processing', False):
            self.report({"WARNING"}, "Cannot clear while extracting labels")
            return {"CANCELLED"}
        if tab.gen_in_progress:
            self.report({"WARNING"}, "Cannot clear while generating images")
            return {"CANCELLED"}

        # Cancel any pending labels queue jobs
        try:
            from mixar.modules.common.job_queue import get_queue
            from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN_EXP_LABELS
            get_queue(FEATURE_SCENE_GEN_EXP_LABELS).clear_completed()
        except Exception:
            pass

        # Reset all tab state
        tab.objects.clear()
        tab.has_result = False
        tab.error_text = ""
        tab.stage_detail = ""
        tab.gen_in_progress = False
        tab.gen_total_count = 0
        tab.gen_completed_count = 0
        tab.gen_failed_count = 0
        tab.rename_allowed = True

        self.report({"INFO"}, "Scene Gen Experimental cleared")
        return {"FINISHED"}


class MIXIE_OT_scene_gen_exp_extract_labels(Operator):
    """Extract labels from the input image"""

    bl_idname = "mixie.scene_gen_exp_extract_labels"
    bl_label = "Extract labels"
    bl_description = "Send the image to the backend for label extraction"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene = context.scene
        tab = _get_tab(context)
        if tab is None:
            self.report({"ERROR"}, "Sidebar properties not found")
            return {"CANCELLED"}

        if getattr(scene, 'mixie_scene_gen_exp_is_processing', False):
            self.report({"WARNING"}, "Already extracting labels")
            return {"CANCELLED"}

        image_bytes = None
        use_selected = getattr(tab, 'use_selected_image', True)

        if use_selected:
            selected = [
                item for item in scene.mixie_moodboard_images
                if item.selected and is_still_item(item)
            ]
            if not selected:
                self.report({"WARNING"}, "Please select an image in the moodboard")
                return {"CANCELLED"}
            try:
                image_bytes = compress_image_for_upload(selected[0].image)
            except Exception as e:
                self.report({"ERROR"}, f"Failed to process image: {e}")
                return {"CANCELLED"}
        else:
            if not tab.reference_image:
                self.report({"WARNING"}, "Please select or upload an image")
                return {"CANCELLED"}
            try:
                image_bytes = compress_image_for_upload(tab.reference_image)
            except Exception as e:
                self.report({"ERROR"}, f"Failed to process image: {e}")
                return {"CANCELLED"}

        try:
            from mixar.modules.moodboard.core.scene_gen_exp_manager import (
                get_scene_gen_exp_manager,
            )
        except ImportError as e:
            self.report({"ERROR"}, f"Scene gen exp manager not available: {e}")
            return {"CANCELLED"}

        manager = get_scene_gen_exp_manager()
        success = manager.submit_job(
            image_bytes=image_bytes,
            min_mask_pixels=int(getattr(tab, 'min_mask_pixels', 2000)),
        )

        if not success:
            self.report({"WARNING"}, "Failed to submit (already running?)")
            return {"CANCELLED"}

        self.report({"INFO"}, "Extracting labels...")
        return {"FINISHED"}


class MIXIE_OT_scene_gen_exp_generate_hp(Operator):
    """Generate HP meshes from selected moodboard images (Step 3)"""

    bl_idname = "mixie.scene_gen_exp_generate_hp"
    bl_label = "Generate HP Meshes"
    bl_description = (
        "Submit image-to-3D Pro generation for selected moodboard images "
        "that were created in Step 2"
    )
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        count = self._count_eligible(context)
        if count == 0:
            self.report({"WARNING"}, "No eligible images for checked labels")
            return {"CANCELLED"}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        tab = _get_tab(context)
        if tab is None:
            self.report({"ERROR"}, "Sidebar properties not found")
            return {"CANCELLED"}

        if not tab.has_result:
            self.report({"WARNING"}, "Run Step 1 first")
            return {"CANCELLED"}

        if getattr(scene, 'mixie_scene_gen_exp_is_processing', False):
            self.report({"WARNING"}, "Step 1 is still running")
            return {"CANCELLED"}

        # Auto-resolve from checked labels' chain_ids
        checked_chain_ids = {
            obj.chain_id for obj in tab.objects
            if obj.selected and obj.chain_id
        }

        images_with_chain_ids = [
            (item.image, item.chain_id)
            for item in scene.mixie_moodboard_images
            if item.image and item.chain_id in checked_chain_ids
        ]

        if not images_with_chain_ids:
            self.report({"WARNING"}, "No eligible images for checked labels")
            return {"CANCELLED"}

        shared_params = {
            "generate_type": tab.hp_generate_type,
            "model_version": tab.hp_model_version,
            "enable_pbr": tab.hp_enable_pbr,
            "face_count": tab.hp_face_count,
            "polygon_type": tab.hp_polygon_type,
        }

        from mixar.modules.moodboard.core.generation_enqueue import (
            enqueue_scene_gen_hp_jobs,
        )
        enqueued = enqueue_scene_gen_hp_jobs(
            images_with_chain_ids=images_with_chain_ids,
            shared_params=shared_params,
            operator=self,
        )

        self.report({"INFO"}, f"Queued {len(enqueued)} HP generation job(s)")
        return {"FINISHED"}

    @staticmethod
    def _count_eligible(context):
        tab = _get_tab(context)
        if tab is None or not tab.has_result:
            return 0
        scene = context.scene
        checked_chain_ids = {
            obj.chain_id for obj in tab.objects
            if obj.selected and obj.chain_id
        }
        return sum(
            1 for item in scene.mixie_moodboard_images
            if item.image and item.chain_id in checked_chain_ids
        )


class MIXIE_OT_scene_gen_exp_generate_lp(Operator):
    """Generate LP meshes from selected HP viewport objects (Step 4)"""

    bl_idname = "mixie.scene_gen_exp_generate_lp"
    bl_label = "Generate LP Meshes"
    bl_description = (
        "Submit retopology for selected viewport objects that were created in Step 3"
    )
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        count = self._count_eligible(context)
        if count == 0:
            self.report({"WARNING"}, "No eligible HP meshes for checked labels")
            return {"CANCELLED"}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        tab = _get_tab(context)
        if tab is None:
            self.report({"ERROR"}, "Sidebar properties not found")
            return {"CANCELLED"}

        if not tab.has_result:
            self.report({"WARNING"}, "Run Step 1 first")
            return {"CANCELLED"}

        # Auto-resolve from checked labels' chain_ids
        checked_chain_ids = {
            obj.chain_id for obj in tab.objects
            if obj.selected and obj.chain_id
        }

        objects_with_chain_ids = [
            (obj, obj["mixar_chain_id"])
            for obj in bpy.data.objects
            if obj.type == 'MESH' and obj.name.endswith("_high")
            and "mixar_chain_id" in obj
            and obj["mixar_chain_id"] in checked_chain_ids
        ]

        if not objects_with_chain_ids:
            self.report({"WARNING"}, "No eligible HP meshes for checked labels")
            return {"CANCELLED"}

        shared_params = {
            "polygon_type": tab.lp_polygon_type,
            "face_level": tab.lp_face_level,
            "post_process": tab.lp_post_process,
        }

        from mixar.modules.moodboard.core.generation_enqueue import (
            enqueue_scene_gen_lp_jobs,
        )
        enqueued = enqueue_scene_gen_lp_jobs(
            context=context,
            objects_with_chain_ids=objects_with_chain_ids,
            shared_params=shared_params,
            operator=self,
        )

        self.report({"INFO"}, f"Queued {len(enqueued)} LP retopology job(s)")
        return {"FINISHED"}

    @staticmethod
    def _count_eligible(context):
        tab = _get_tab(context)
        if tab is None or not tab.has_result:
            return 0
        checked_chain_ids = {
            obj.chain_id for obj in tab.objects
            if obj.selected and obj.chain_id
        }
        return sum(
            1 for obj in bpy.data.objects
            if obj.type == 'MESH' and obj.name.endswith("_high")
            and "mixar_chain_id" in obj
            and obj["mixar_chain_id"] in checked_chain_ids
        )


classes = (
    MIXIE_OT_scene_gen_exp_pick_image,
    MIXIE_OT_scene_gen_exp_remove_image,
    MIXIE_OT_scene_gen_exp_clear,
    MIXIE_OT_scene_gen_exp_extract_labels,
    MIXIE_OT_scene_gen_exp_toggle_all,
    MIXIE_OT_scene_gen_exp_generate_images,
    MIXIE_OT_scene_gen_exp_generate_hp,
    MIXIE_OT_scene_gen_exp_generate_lp,
)


# Scene Gen Experimental disabled — operators intentionally not registered.
def register():
    return


def unregister():
    return
