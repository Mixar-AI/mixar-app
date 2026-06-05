# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Reconstruction Operators

Operators for scene reconstruction from images using the SAM3D pipeline.
"""

import os
import subprocess
import sys
import time

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.image_utils import (
    add_image_to_moodboard,
    compress_image_for_upload,
    compress_file_for_upload,
    load_image_from_url,
)
from mixar.modules.moodboard.core.scene_recon_submission import (
    on_prompt_error as _on_prompt_error,
    submit_recon_job as _submit_recon_from_callback,
)
from mixar.modules.common.utils.file_select_utils import file_select_guard, mark_file_select_executed
from mixar.modules.moodboard.core.generate_progress import start_progress, complete_progress, reset_progress

logger = get_logger(__name__)


class MIXIE_OT_scene_recon_pick_image(Operator):
    """Select an image file for scene reconstruction"""

    bl_idname = "mixie.scene_recon_pick_image"
    bl_label = "Pick Image"
    bl_description = "Select an image file for scene reconstruction"
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

        # Store path and display name in tab properties
        scene = context.scene
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            sidebar = scene.mixie_moodboard_sidebar
            if hasattr(sidebar, 'tab_scene_recon'):
                sidebar.tab_scene_recon.image_path = filepath
                sidebar.tab_scene_recon.image_name = os.path.basename(filepath)
                self.report({"INFO"}, f"Selected '{os.path.basename(filepath)}'")
                mark_file_select_executed(self)
                return {"FINISHED"}

        self.report({"ERROR"}, "Sidebar properties not found")
        return {"CANCELLED"}


class MIXIE_OT_scene_recon_remove_image(Operator):
    """Remove the input image from Scene Reconstruction tab"""

    bl_idname = "mixie.scene_recon_remove_image"
    bl_label = "Remove Image"
    bl_description = "Remove the input image"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            sidebar = scene.mixie_moodboard_sidebar
            if hasattr(sidebar, 'tab_scene_recon'):
                sidebar.tab_scene_recon.image_path = ""
                sidebar.tab_scene_recon.image_name = ""
                self.report({"INFO"}, "Input image removed")
                return {"FINISHED"}

        self.report({"ERROR"}, "Sidebar properties not found")
        return {"CANCELLED"}


class MIXIE_OT_scene_recon_generate(Operator):
    """Submit a scene reconstruction job"""

    bl_idname = "mixie.scene_recon_generate"
    bl_label = "Reconstruct Scene"
    bl_description = "Reconstruct 3D scene from the input image"
    bl_options = {"REGISTER"}

    from_chat: bpy.props.BoolProperty(
        name="From Chat",
        description="Called from chat context - use prompt from scene property",
        default=False,
    )

    chat_prompt: bpy.props.StringProperty(
        name="Chat Prompt",
        description="Prompt text when called from chat",
        default="",
    )

    chat_image_name: bpy.props.StringProperty(
        name="Chat Image Name",
        description="Name of attached image in bpy.data.images when called from chat",
        default="",
    )

    def execute(self, context):
        scene = context.scene

        # Check not already generating
        if hasattr(scene, 'mixie_scene_recon_is_generating') and scene.mixie_scene_recon_is_generating:
            self.report({"WARNING"}, "Generation already in progress")
            return {"CANCELLED"}

        # Chat context
        if self.from_chat:
            prompt = self.chat_prompt.strip()
            image_name = self.chat_image_name.strip()

            if image_name:
                # Image attached — use it directly, skip image generation
                return self._start_from_image_chat(scene, image_name, prompt)
            elif prompt:
                # Prompt only — generate image first, then reconstruct
                return self._start_from_prompt_chat(scene, prompt)
            else:
                self.report({"ERROR"}, "Please enter a prompt or attach an image")
                return {"CANCELLED"}

        # Get tab properties
        sidebar_tab = None
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            sidebar = scene.mixie_moodboard_sidebar
            if hasattr(sidebar, 'tab_scene_recon'):
                sidebar_tab = sidebar.tab_scene_recon

        if not sidebar_tab:
            self.report({"ERROR"}, "Sidebar properties not found")
            return {"CANCELLED"}

        # Get image bytes based on toggle state
        image_bytes = None
        use_selected = getattr(sidebar_tab, 'use_selected_image', False)

        if use_selected:
            # Use first selected moodboard image
            selected = [
                item
                for item in scene.mixie_moodboard_images
                if item.selected and item.image
            ]
            if not selected:
                self.report({"WARNING"}, "Please select an image in the moodboard")
                return {"CANCELLED"}

            try:
                image_bytes = compress_image_for_upload(selected[0].image)
                logger.debug("Using moodboard image: %s", selected[0].image.name)
            except Exception as e:
                self.report({"ERROR"}, f"Failed to process image: {e}")
                return {"CANCELLED"}
        else:
            # Use file picker image or text prompt
            image_path = getattr(sidebar_tab, 'image_path', '')
            if image_path and os.path.isfile(image_path):
                try:
                    image_bytes = compress_file_for_upload(image_path)
                    logger.debug("Using file: %s", image_path)
                except Exception as e:
                    self.report({"ERROR"}, f"Failed to read image: {e}")
                    return {"CANCELLED"}
            else:
                # No file picked - check for text prompt
                prompt = getattr(sidebar_tab, 'prompt', '').strip()
                if not prompt:
                    self.report(
                        {"WARNING"},
                        "Please select an input image or describe a scene"
                    )
                    return {"CANCELLED"}
                # Generate image from prompt, then chain to scene recon
                return self._start_from_prompt(scene, sidebar_tab, prompt)

        start_progress('scene_recon')
        success = _submit_recon_from_callback(
            scene, sidebar_tab, image_bytes,
            generate_mesh=getattr(sidebar_tab, 'generate_mesh', True),
            min_mask_pixels=getattr(sidebar_tab, 'min_mask_pixels', 2000),
            mesh_postprocess=getattr(sidebar_tab, 'mesh_postprocess', True),
            texture_baking=getattr(sidebar_tab, 'texture_baking', False),
            vertex_color=getattr(sidebar_tab, 'vertex_color', True),
            save_to_library=getattr(sidebar_tab, 'save_to_library', False),
            asset_library_path=getattr(sidebar_tab, 'asset_library_path', ''),
        )

        if not success:
            self.report({"WARNING"}, "Failed to submit job (already generating?)")
            return {"CANCELLED"}

        self.report({"INFO"}, "Scene reconstruction started...")
        return {"FINISHED"}

    def _start_from_prompt(self, scene, sidebar_tab, prompt):
        """Generate an image from prompt, add to moodboard, then start recon."""
        try:
            from mixar.modules.common.api import get_imagegen_service
        except ImportError as e:
            self.report({"ERROR"}, f"Image generation service not available: {e}")
            return {"CANCELLED"}

        # Set generating state to show loading UI
        scene.mixie_scene_recon_is_generating = True
        start_progress('scene_recon')
        sidebar_tab.stage_name = "Generating scene image..."
        sidebar_tab.stage_detail = "Creating image from description"
        sidebar_tab.error_text = ""
        sidebar_tab.phase = ""

        for area in bpy.context.screen.areas:
            if area.type == "MIXIE":
                area.tag_redraw()

        service = get_imagegen_service()

        # Append SAM3D-aligned suffix to guide image generation
        _SCENE_RECON_PROMPT_SUFFIX = (
            ", rendered as a single, cohesive 3D scene situated on a distinct"
            " ground plane against a stark white background. Use flat, evenly"
            " distributed diffuse lighting with absolutely no harsh, baked-in"
            " cast shadows to ensure clear surface definition. The camera must"
            " be a standard 50mm lens at an eye-level perspective, displaying"
            " realistic spatial depth, clear vanishing points, and standard"
            " 3-point perspective. STRICTLY AVOID isometric, STRICTLY AVOID orthographic,"
            " STRICTLY AVOID sprite-sheet, STRICTLY AVOID top-down projections."
        )
        stored_prompt = prompt + _SCENE_RECON_PROMPT_SUFFIX
        generate_mesh = getattr(sidebar_tab, 'generate_mesh', True)
        min_mask_pixels = getattr(sidebar_tab, 'min_mask_pixels', 2000)
        mesh_postprocess = getattr(sidebar_tab, 'mesh_postprocess', True)
        texture_baking = getattr(sidebar_tab, 'texture_baking', False)
        vertex_color = getattr(sidebar_tab, 'vertex_color', True)
        save_to_lib = getattr(sidebar_tab, 'save_to_library', False)
        lib_path = getattr(sidebar_tab, 'asset_library_path', '')

        def on_imagegen_success(response):
            try:
                if not response.success:
                    error_msg = (
                        getattr(response, "error", None) or "Image generation failed"
                    )
                    _on_prompt_error(scene, sidebar_tab, f"API Error: {error_msg}")
                    return

                data = response.data
                if not data:
                    _on_prompt_error(
                        scene, sidebar_tab, "No data from image generation"
                    )
                    return

                if isinstance(data, dict):
                    status = data.get("status", "").lower()
                    if status in ("failure", "error"):
                        _on_prompt_error(
                            scene, sidebar_tab,
                            data.get("message", "Unknown error"),
                        )
                        return
                    if "data" in data and isinstance(data["data"], dict):
                        data = data["data"]

                # Extract first image URL
                image_url = None
                if isinstance(data, dict):
                    for img_item in data.get("images", []):
                        if isinstance(img_item, dict) and "url" in img_item:
                            image_url = img_item["url"]
                            break
                        elif isinstance(img_item, str):
                            image_url = img_item
                            break
                    if not image_url:
                        image_url = data.get("image_url")

                if not image_url:
                    _on_prompt_error(
                        scene, sidebar_tab, "No image URL in response"
                    )
                    return

                # Download image and add to moodboard
                timestamp = int(time.time())
                img = load_image_from_url(image_url, f"scene_recon_{timestamp}")
                add_image_to_moodboard(img, stored_prompt)
                logger.info("Generated image added to moodboard: %s", img.name)

                # Get image bytes for scene reconstruction
                image_bytes = compress_image_for_upload(img)

                # Update status and submit scene reconstruction
                sidebar_tab.stage_name = "Starting reconstruction..."
                sidebar_tab.stage_detail = ""
                _submit_recon_from_callback(
                    scene, sidebar_tab, image_bytes,
                    generate_mesh, min_mask_pixels,
                    mesh_postprocess, texture_baking, vertex_color,
                    save_to_library=save_to_lib,
                    asset_library_path=lib_path,
                )

            except Exception as e:
                logger.error("Error in image generation callback", exc_info=True)
                _on_prompt_error(scene, sidebar_tab, f"Error: {e}")

        def on_imagegen_error(error):
            _on_prompt_error(
                scene, sidebar_tab, f"Image generation failed: {error}"
            )

        def on_imagegen_complete(async_response):
            if scene.mixie_scene_recon_is_generating:
                error = getattr(async_response, "error", None)
                response = getattr(async_response, "response", None)
                if error:
                    _on_prompt_error(
                        scene, sidebar_tab, f"Request failed: {error}"
                    )
                elif response and not response.success:
                    pass  # on_success already handled this

        try:
            service.generate_async(
                prompt=stored_prompt,
                model="pro",
                aspect_ratio="4:3",
                resolution="1K",
                number_of_images=1,
                on_success=on_imagegen_success,
                on_error=on_imagegen_error,
                on_complete=on_imagegen_complete,
            )
        except Exception as e:
            scene.mixie_scene_recon_is_generating = False
            reset_progress('scene_recon')
            self.report({"ERROR"}, f"Failed to start image generation: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Generating scene image from description...")
        return {"FINISHED"}

    def _start_from_image_chat(self, scene, image_name, prompt=""):
        """Reconstruct scene from an attached image (no image generation step)."""
        img = bpy.data.images.get(image_name)
        if not img:
            self.report({"ERROR"}, f"Image '{image_name}' not found")
            return {"CANCELLED"}

        try:
            image_bytes = compress_image_for_upload(img)
        except Exception as e:
            self.report({"ERROR"}, f"Failed to process image: {e}")
            return {"CANCELLED"}

        scene.mixie_scene_recon_is_generating = True
        scene.mixie_scene_recon_error = ""
        start_progress('scene_recon')

        for area in bpy.context.screen.areas:
            if area.type == "MIXIE":
                area.tag_redraw()

        # Add the image to moodboard for reference
        add_image_to_moodboard(img, prompt or image_name)

        # Submit scene reconstruction directly
        _submit_recon_from_callback(
            scene, None, image_bytes,
            generate_mesh=True,
            min_mask_pixels=2000,
            mesh_postprocess=True,
            texture_baking=True,
            vertex_color=True,
        )

        self.report({"INFO"}, "Scene reconstruction started from image...")
        return {"FINISHED"}

    def _start_from_prompt_chat(self, scene, prompt):
        """Generate scene from prompt when called from chat."""
        try:
            from mixar.modules.common.api import get_imagegen_service
        except ImportError as e:
            self.report({"ERROR"}, f"Image generation service not available: {e}")
            return {"CANCELLED"}

        scene.mixie_scene_recon_is_generating = True
        scene.mixie_scene_recon_error = ""
        start_progress('scene_recon')

        for area in bpy.context.screen.areas:
            if area.type == "MIXIE":
                area.tag_redraw()

        service = get_imagegen_service()

        _SCENE_RECON_PROMPT_SUFFIX = (
            ", rendered as a single, cohesive 3D scene situated on a distinct"
            " ground plane against a stark white background. Use flat, evenly"
            " distributed diffuse lighting with absolutely no harsh, baked-in"
            " cast shadows to ensure clear surface definition. The camera must"
            " be a standard 50mm lens at an eye-level perspective, displaying"
            " realistic spatial depth, clear vanishing points, and standard"
            " 3-point perspective. STRICTLY AVOID isometric, STRICTLY AVOID orthographic,"
            " STRICTLY AVOID sprite-sheet, STRICTLY AVOID top-down projections."
        )
        stored_prompt = prompt + _SCENE_RECON_PROMPT_SUFFIX

        def _on_chat_error(message):
            logger.error("%s", message)
            def _show():
                try:
                    reset_progress('scene_recon')
                    scene.mixie_scene_recon_is_generating = False
                    scene.mixie_scene_recon_error = message
                    for window in bpy.context.window_manager.windows:
                        for area in window.screen.areas:
                            if area.type in ("MIXIE", "MIXIE_CHAT"):
                                area.tag_redraw()
                except Exception:
                    pass
                return None
            bpy.app.timers.register(_show, first_interval=0)

        def on_imagegen_success(response):
            try:
                if not response.success:
                    error_msg = getattr(response, "error", None) or "Image generation failed"
                    _on_chat_error(f"API Error: {error_msg}")
                    return

                data = response.data
                if not data:
                    _on_chat_error("No data from image generation")
                    return

                if isinstance(data, dict):
                    status = data.get("status", "").lower()
                    if status in ("failure", "error"):
                        _on_chat_error(data.get("message", "Unknown error"))
                        return
                    if "data" in data and isinstance(data["data"], dict):
                        data = data["data"]

                # Extract first image URL
                image_url = None
                if isinstance(data, dict):
                    for img_item in data.get("images", []):
                        if isinstance(img_item, dict) and "url" in img_item:
                            image_url = img_item["url"]
                            break
                        elif isinstance(img_item, str):
                            image_url = img_item
                            break
                    if not image_url:
                        image_url = data.get("image_url")

                if not image_url:
                    _on_chat_error("No image URL in response")
                    return

                # Download image and add to moodboard
                timestamp = int(time.time())
                img = load_image_from_url(image_url, f"scene_recon_{timestamp}")
                add_image_to_moodboard(img, stored_prompt)
                logger.info("Generated image added to moodboard: %s", img.name)

                # Get image bytes for scene reconstruction
                image_bytes = compress_image_for_upload(img)

                # Submit scene reconstruction with defaults
                _submit_recon_from_callback(
                    scene, None, image_bytes,
                    generate_mesh=True,
                    min_mask_pixels=2000,
                    mesh_postprocess=True,
                    texture_baking=True,
                    vertex_color=True,
                )

            except Exception as e:
                logger.error("Error in chat scene recon callback", exc_info=True)
                _on_chat_error(f"Error: {e}")

        def on_imagegen_error(error):
            _on_chat_error(f"Image generation failed: {error}")

        def on_imagegen_complete(async_response):
            if scene.mixie_scene_recon_is_generating:
                error = getattr(async_response, "error", None)
                if error:
                    _on_chat_error(f"Request failed: {error}")

        try:
            service.generate_async(
                prompt=stored_prompt,
                model="pro",
                aspect_ratio="4:3",
                resolution="1K",
                number_of_images=1,
                on_success=on_imagegen_success,
                on_error=on_imagegen_error,
                on_complete=on_imagegen_complete,
            )
        except Exception as e:
            scene.mixie_scene_recon_is_generating = False
            reset_progress('scene_recon')
            self.report({"ERROR"}, f"Failed to start image generation: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Generating scene from description...")
        return {"FINISHED"}


class MIXIE_OT_scene_recon_cancel(Operator):
    """Cancel the active scene reconstruction job"""

    bl_idname = "mixie.scene_recon_cancel"
    bl_label = "Cancel"
    bl_description = "Cancel the current scene reconstruction"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            from mixar.modules.moodboard.core.scene_recon_manager import get_scene_recon_manager
        except ImportError as e:
            self.report({"ERROR"}, f"Scene recon manager not available: {e}")
            return {"CANCELLED"}

        manager = get_scene_recon_manager()
        if manager.cancel_job():
            self.report({"INFO"}, "Scene reconstruction cancelled")
            return {"FINISHED"}

        self.report({"WARNING"}, "No active job to cancel")
        return {"CANCELLED"}


class MIXIE_OT_scene_recon_open_folder(Operator):
    """Open the folder containing the result file"""

    bl_idname = "mixie.scene_recon_open_folder"
    bl_label = "Open Folder"
    bl_description = "Open the folder containing the result file"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene = context.scene
        result_path = ""
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            sidebar = scene.mixie_moodboard_sidebar
            if hasattr(sidebar, 'tab_scene_recon'):
                result_path = sidebar.tab_scene_recon.result_path

        if not result_path:
            self.report({"WARNING"}, "No result file available")
            return {"CANCELLED"}

        folder = os.path.dirname(result_path)
        if not os.path.isdir(folder):
            self.report({"ERROR"}, f"Folder not found: {folder}")
            return {"CANCELLED"}

        # Open folder in file explorer (cross-platform).
        # Safe: list form avoids shell injection; folder is derived from
        # os.path.dirname on a path stored in our own scene properties.
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

        return {"FINISHED"}


classes = (
    MIXIE_OT_scene_recon_pick_image,
    MIXIE_OT_scene_recon_remove_image,
    MIXIE_OT_scene_recon_generate,
    MIXIE_OT_scene_recon_cancel,
    MIXIE_OT_scene_recon_open_folder,
)
