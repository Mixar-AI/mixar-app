# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image to 3D Operators

Operators for 3D model generation from images using the dynamic v2 API.
Uses a generation ID to prevent duplicate model imports when a user
re-triggers generation before the previous request completes.
"""

import datetime
import os
import tempfile
import urllib.request

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.image_utils import compress_for_service
from mixar.modules.common.utils.mixie_space_utils import show_generation_error
from ...core.generate_progress import start_progress, complete_progress, reset_progress

logger = get_logger(__name__)

# Monotonically increasing ID to track the "current" generation request.
# When a new generation starts, this is incremented. Callbacks from stale
# (superseded) requests compare their captured ID against this value and
# skip the import if they no longer match.
_current_generation_id = 0


def download_and_import_glb(url: str, model_name: str = "generated_model") -> bool:
    """
    Download a GLB file from URL to temp directory and import it into Blender.

    Args:
        url: URL to download the GLB file from
        model_name: Name to give the imported model

    Returns:
        True if successful, False otherwise
    """
    logger.info("Downloading GLB from: %s...", url[:100])

    temp_dir = os.path.join(tempfile.gettempdir(), "mixar_image_to_3d")
    os.makedirs(temp_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_filepath = os.path.join(temp_dir, f"{model_name}_{timestamp}.glb")

    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            glb_data = response.read()

        logger.debug("Downloaded %d bytes", len(glb_data))

        with open(temp_filepath, "wb") as f:
            f.write(glb_data)

        logger.debug("Saved to: %s", temp_filepath)

        bpy.ops.import_scene.gltf(filepath=temp_filepath)

        logger.info("Successfully imported GLB model")

        imported_objects = [obj for obj in bpy.context.selected_objects]
        if imported_objects:
            logger.info("Imported %d object(s)", len(imported_objects))
            for obj in imported_objects:
                logger.debug("  - %s", obj.name)

        return True

    except urllib.error.URLError as e:
        logger.error("Download failed: %s", e)
        return False
    except Exception as e:
        logger.error("Import failed: %s", e, exc_info=True)
        return False


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

        # Guard: prevent duplicate generation while one is already in progress
        if getattr(scene, 'mixie_image_to_3d_is_generating', False):
            self.report({"WARNING"}, "Generation already in progress")
            return {"CANCELLED"}

        # Check if called from sidebar context - prefer sidebar properties
        sidebar_tab = None
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            sidebar = scene.mixie_moodboard_sidebar
            if hasattr(sidebar, 'tab_image_to_3d'):
                sidebar_tab = sidebar.tab_image_to_3d

        # Determine model to use
        if self.from_chat:
            # Use default model from cache for chat context
            try:
                from mixar.bootstrap.model_3d_cache import get_default_model_name

                model_name = get_default_model_name()
                if not model_name:
                    self.report(
                        {"WARNING"}, "No models available - please wait for models to load"
                    )
                    return {"CANCELLED"}
            except ImportError:
                self.report({"WARNING"}, "Model cache not available")
                return {"CANCELLED"}
        else:
            # Get model from sidebar properties or fallback to global
            if sidebar_tab:
                model_name = getattr(sidebar_tab, 'model', '')
            elif hasattr(scene, 'mixie_image_to_3d_model'):
                model_name = scene.mixie_image_to_3d_model
            else:
                model_name = ''

            if model_name in ("LOADING", "ERROR", "NONE", ""):
                # Scene property has invalid value, try to use first cached model
                try:
                    from mixar.bootstrap.model_3d_cache import get_default_model_name
                    model_name = get_default_model_name()
                except ImportError:
                    pass

            if not model_name or model_name in ("LOADING", "ERROR", "NONE", ""):
                self.report(
                    {"WARNING"}, "Please wait for models to load or check connection"
                )
                return {"CANCELLED"}

        # Get the input image based on context
        image = None

        if self.from_chat:
            # Chat context: use image set by chat handler in global property
            if hasattr(scene, 'mixie_image_to_3d_image'):
                image = scene.mixie_image_to_3d_image
                if image:
                    logger.info("Using chat-attached image: %s", image.name)
                else:
                    self.report({"WARNING"}, "Please attach an image in chat")
                    return {"CANCELLED"}
            else:
                self.report({"WARNING"}, "No input image available")
                return {"CANCELLED"}
        elif sidebar_tab:
            # Sidebar context: check toggle state
            use_selected = getattr(sidebar_tab, 'use_selected_image', False)

            if use_selected:
                # Toggle ON: use first selected moodboard image (max 1)
                selected = [
                    item
                    for item in scene.mixie_moodboard_images
                    if item.selected and item.image
                ]
                if selected:
                    image = selected[0].image
                    logger.info("Using selected moodboard image: %s", image.name)
                else:
                    self.report({"WARNING"}, "Please select an image in the moodboard")
                    return {"CANCELLED"}
            else:
                # Toggle OFF: use uploaded reference_image
                image = getattr(sidebar_tab, 'reference_image', None)
                if image:
                    logger.info("Using uploaded image: %s", image.name)
                else:
                    self.report({"WARNING"}, "Please add an input image")
                    return {"CANCELLED"}
        else:
            # Fallback to global properties for popup context
            if hasattr(scene, 'mixie_image_to_3d_use_selected') and scene.mixie_image_to_3d_use_selected:
                selected = [
                    item
                    for item in scene.mixie_moodboard_images
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

        # Get prompt (optional) from appropriate source
        if sidebar_tab:
            prompt = getattr(sidebar_tab, 'prompt', '').strip() or None
        elif hasattr(scene, 'mixie_image_to_3d_prompt'):
            prompt = scene.mixie_image_to_3d_prompt.strip() or None
        else:
            prompt = None

        # Import API service
        try:
            from mixar.modules.common.api import get_model_3d_gen_service
        except ImportError as e:
            self.report({"ERROR"}, f"Model 3D Gen API service not available: {e}")
            return {"CANCELLED"}

        service = get_model_3d_gen_service()

        # Set generating flag and clear error
        scene.mixie_image_to_3d_is_generating = True
        scene.mixie_image_to_3d_error = ""
        start_progress('image_to_3d')

        # Increment generation ID so stale callbacks are ignored
        global _current_generation_id
        _current_generation_id += 1
        my_generation_id = _current_generation_id

        # Store model name for use in callbacks
        stored_model_name = model_name

        def show_error(message: str):
            show_generation_error(
                scene, "Image to 3D", message,
                "mixie_image_to_3d_is_generating", "mixie_image_to_3d_error",
            )

        def on_success(response):
            """Handle successful generation response."""
            # Skip if this callback belongs to a superseded generation
            if my_generation_id != _current_generation_id:
                logger.info(
                    "Ignoring stale generation response (id=%d, current=%d)",
                    my_generation_id, _current_generation_id,
                )
                return

            # Bail out if user cancelled
            if not getattr(scene, 'mixie_image_to_3d_is_generating', False):
                logger.info("[Image to 3D] Generation cancelled, ignoring response")
                return

            logger.info("Generation complete")

            try:
                if not response.success:
                    error_msg = getattr(response, "error", None) or "Generation failed"
                    show_error(f"API Error: {error_msg}")
                    return

                data = response.data
                if not data:
                    show_error("No data received from server")
                    return

                # Handle response structure
                if isinstance(data, dict):
                    status = data.get("status", "").lower()
                    if status in ("failure", "error"):
                        error_message = data.get("message", "Unknown error from server")
                        show_error(f"Server Error: {error_message}")
                        return

                    # Handle nested data structure
                    if "data" in data and isinstance(data["data"], dict):
                        data = data["data"]

                model_url = data.get("model_url") if isinstance(data, dict) else None
                scene.mixie_image_to_3d_is_generating = False
                complete_progress('image_to_3d')

                for area in bpy.context.screen.areas:
                    if area.type == "MIXIE":
                        area.tag_redraw()

                if model_url:
                    logger.info("Downloading and importing model...")
                    success = download_and_import_glb(model_url, stored_model_name)

                    if success:
                        bpy.ops.ed.undo_push(message="Image to 3D: Import Model")

                        def draw_success(self, context):
                            self.layout.label(text="3D model generated and imported!")

                        bpy.context.window_manager.popup_menu(
                            draw_success, title="Image to 3D", icon="CHECKMARK"
                        )
                    else:

                        def draw_warning(self, context):
                            self.layout.label(text="Model generated but import failed.")
                            self.layout.label(text="Check console for details.")

                        bpy.context.window_manager.popup_menu(
                            draw_warning, title="Image to 3D", icon="ERROR"
                        )
                else:
                    logger.info("No model URL in response")

                    def draw_warning(self, context):
                        self.layout.label(
                            text="Generation completed but no model URL received."
                        )

                    bpy.context.window_manager.popup_menu(
                        draw_warning, title="Image to 3D", icon="INFO"
                    )

            except Exception as e:
                logger.error("Error processing response: %s", e, exc_info=True)
                show_error(f"Error processing response: {e}")

        def on_error(error):
            """Handle generation error."""
            # Skip if this callback belongs to a superseded generation
            if my_generation_id != _current_generation_id:
                logger.info(
                    "Ignoring stale generation error (id=%d, current=%d)",
                    my_generation_id, _current_generation_id,
                )
                return

            # Bail out if user cancelled
            if not getattr(scene, 'mixie_image_to_3d_is_generating', False):
                return

            error_str = str(error) if error else "Unknown error"
            reset_progress('image_to_3d')
            show_error(f"Request failed: {error_str}")

        # Call the unified generate API
        try:
            service.generate_async(
                image=image_bytes,
                model_name=model_name,
                prompt=prompt,
                parameters=None,  # Use server defaults
                on_success=on_success,
                on_error=on_error,
            )
        except Exception as e:
            scene.mixie_image_to_3d_is_generating = False
            reset_progress('image_to_3d')
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"3D model generation started using {model_name}...")
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
