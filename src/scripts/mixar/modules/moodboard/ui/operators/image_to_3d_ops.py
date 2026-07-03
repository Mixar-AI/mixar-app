# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image to 3D Operators

Operators for 3D model generation from images using the unified generation queue.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.image_utils import compress_for_service

logger = get_logger(__name__)


class MIXIE_OT_image_to_3d_generate(Operator):
    """Generate a 3D model from an image"""

    bl_idname = "mixie.image_to_3d_generate"
    bl_label = "Generate 3D Model"
    bl_description = "Generate a 3D model from the selected image"
    bl_options = {"REGISTER"}

    from_chat: bpy.props.BoolProperty(
        name="From Chat",
        description="Called from chat context - use defaults",
        default=False,
    )

    def execute(self, context):
        scene = context.scene

        # Check if called from sidebar context - prefer sidebar properties
        sidebar_tab = None
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            sidebar = scene.mixie_moodboard_sidebar
            if hasattr(sidebar, 'tab_image_to_3d'):
                sidebar_tab = sidebar.tab_image_to_3d

        # Determine model to use
        if self.from_chat:
            try:
                from mixar.bootstrap.model_3d_cache import get_default_model_name
                model_name = get_default_model_name()
                if not model_name:
                    self.report({"WARNING"}, "No models available - please wait for models to load")
                    return {"CANCELLED"}
            except ImportError:
                self.report({"WARNING"}, "Model cache not available")
                return {"CANCELLED"}
        else:
            if sidebar_tab:
                model_name = getattr(sidebar_tab, 'model', '')
            elif hasattr(scene, 'mixie_image_to_3d_model'):
                model_name = scene.mixie_image_to_3d_model
            else:
                model_name = ''

            if model_name in ("LOADING", "ERROR", "NONE", ""):
                try:
                    from mixar.bootstrap.model_3d_cache import get_default_model_name
                    model_name = get_default_model_name()
                except ImportError:
                    pass

            if not model_name or model_name in ("LOADING", "ERROR", "NONE", ""):
                self.report({"WARNING"}, "Please wait for models to load or check connection")
                return {"CANCELLED"}

        # Get the input image based on context
        image = None

        if self.from_chat:
            if hasattr(scene, 'mixie_image_to_3d_image'):
                image = scene.mixie_image_to_3d_image
                if not image:
                    self.report({"WARNING"}, "Please attach an image in chat")
                    return {"CANCELLED"}
            else:
                self.report({"WARNING"}, "No input image available")
                return {"CANCELLED"}
        elif sidebar_tab:
            use_selected = getattr(sidebar_tab, 'use_selected_image', False)
            if use_selected:
                selected = [
                    item for item in scene.mixie_moodboard_images
                    if item.selected and item.image
                ]
                if selected:
                    image = selected[0].image
                else:
                    self.report({"WARNING"}, "Please select an image in the moodboard")
                    return {"CANCELLED"}
            else:
                image = getattr(sidebar_tab, 'reference_image', None)
                if not image:
                    self.report({"WARNING"}, "Please add an input image")
                    return {"CANCELLED"}
        else:
            if hasattr(scene, 'mixie_image_to_3d_use_selected') and scene.mixie_image_to_3d_use_selected:
                selected = [
                    item for item in scene.mixie_moodboard_images
                    if item.selected and item.image
                ]
                if selected:
                    image = selected[0].image
                else:
                    self.report({"WARNING"}, "No image selected in moodboard")
                    return {"CANCELLED"}
            elif hasattr(scene, 'mixie_image_to_3d_image'):
                image = scene.mixie_image_to_3d_image
                if not image:
                    self.report({"WARNING"}, "No input image selected")
                    return {"CANCELLED"}
            else:
                self.report({"WARNING"}, "No input image available")
                return {"CANCELLED"}

        # Convert image to bytes
        try:
            image_bytes = compress_for_service(image, "image_to_3d")
        except Exception as e:
            self.report({"ERROR"}, f"Failed to process image: {e}")
            return {"CANCELLED"}

        # Get prompt (optional)
        if sidebar_tab:
            prompt = getattr(sidebar_tab, 'prompt', '').strip() or None
        elif hasattr(scene, 'mixie_image_to_3d_prompt'):
            prompt = scene.mixie_image_to_3d_prompt.strip() or None
        else:
            prompt = None

        # Enqueue via generation queue
        try:
            from ...core.model_3d_queue import enqueue_model_3d_job
            enqueue_model_3d_job(
                image_bytes=image_bytes,
                model_name=model_name,
                prompt=prompt,
                label=image.name if image else model_name,
            )
        except Exception as e:
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        from mixar.modules.common.job_queue.constants import FEATURE_MODEL_3D
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
        mark_enqueued(FEATURE_MODEL_3D)
        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}


classes = (
    MIXIE_OT_image_to_3d_generate,
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
        unregister_class(cls)
