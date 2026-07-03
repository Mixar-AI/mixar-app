# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent Image Gen Operator

Simplified operator for agent-driven image generation.
Takes all parameters as properties for direct invocation.
"""

import time

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from mixar.modules.common.utils.image_utils import (
    add_image_to_moodboard,
    compress_image_for_upload,
    load_image_from_url,
)
from ...core.generate_progress import start_progress, reset_progress, complete_progress


class MIXIE_OT_agent_imagegen(Operator):
    """Generate images using AI for agent use"""

    bl_idname = "mixie.agent_imagegen"
    bl_label = "Agent Generate Image"
    bl_description = "Generate AI images via agent"
    bl_options = {"REGISTER"}

    # Model selection (flash or pro)
    model: bpy.props.EnumProperty(
        name="Model",
        description="Model to use for generation",
        items=[
            ("flash", "Flash", "Gemini 2.5 Flash - Fast generation"),
            ("pro", "Pro", "Gemini 3 Pro - Higher quality"),
        ],
        default="flash",
    )

    # Required
    prompt: bpy.props.StringProperty(
        name="Prompt",
        description="Text description of desired image",
        default="",
    )

    # Style preset
    style: bpy.props.EnumProperty(
        name="Style",
        description="Style preset to apply",
        items=[
            ("none", "None", "No style preset"),
            ("photorealistic", "Photorealistic", "Photorealistic style"),
            ("artistic", "Artistic", "Artistic painterly style"),
            ("3d_render", "3D Render", "3D rendered style"),
            ("concept_art", "Concept Art", "Concept art style"),
            ("anime", "Anime", "Anime illustration style"),
        ],
        default="none",
    )

    # Aspect ratio
    aspect_ratio: bpy.props.EnumProperty(
        name="Aspect Ratio",
        description="Output aspect ratio",
        items=[
            ("1:1", "1:1", "Square"),
            ("2:3", "2:3", "Portrait 2:3"),
            ("3:2", "3:2", "Landscape 3:2"),
            ("3:4", "3:4", "Portrait 3:4"),
            ("4:3", "4:3", "Landscape 4:3"),
            ("4:5", "4:5", "Portrait 4:5"),
            ("5:4", "5:4", "Landscape 5:4"),
            ("9:16", "9:16", "Vertical 9:16"),
            ("16:9", "16:9", "Widescreen 16:9"),
            ("21:9", "21:9", "Ultra-wide 21:9 (pro only)"),
        ],
        default="1:1",
    )

    # Resolution (pro model only)
    resolution: bpy.props.EnumProperty(
        name="Resolution",
        description="Output resolution (pro model only)",
        items=[
            ("1K", "1K", "1K resolution"),
            ("2K", "2K", "2K resolution"),
            ("4K", "4K", "4K resolution"),
        ],
        default="1K",
    )

    # Number of images
    number_of_images: bpy.props.IntProperty(
        name="Number of Images",
        description="Number of images to generate (1-4)",
        default=1,
        min=1,
        max=4,
    )

    # Negative prompt
    negative_prompt: bpy.props.StringProperty(
        name="Negative Prompt",
        description="What to avoid in generation",
        default="",
    )

    # Reference image names (comma-separated)
    reference_image_names: bpy.props.StringProperty(
        name="Reference Images",
        description="Comma-separated list of image names from bpy.data.images",
        default="",
    )

    # Add to moodboard
    add_to_moodboard: bpy.props.BoolProperty(
        name="Add to Moodboard",
        description="Add generated images to moodboard",
        default=True,
    )

    def execute(self, context):
        scene = context.scene

        # Validate prompt
        if not self.prompt or not self.prompt.strip():
            self.report({"ERROR"}, "Prompt is required")
            return {"CANCELLED"}

        model = self.model
        prompt = self.prompt.strip()

        # Validate aspect ratio for flash model (doesn't support 21:9)
        if model == "flash" and self.aspect_ratio == "21:9":
            self.report({"ERROR"}, "Flash model does not support 21:9 aspect ratio")
            return {"CANCELLED"}

        # Get max reference images for model
        max_refs = 14 if model == "pro" else 3

        # Collect reference images
        reference_image_bytes = []
        if self.reference_image_names:
            image_names = [n.strip() for n in self.reference_image_names.split(",") if n.strip()]
            for name in image_names:
                img = bpy.data.images.get(name)
                if img and img.has_data:
                    try:
                        img_bytes = compress_image_for_upload(img)
                        reference_image_bytes.append(img_bytes)
                        if len(reference_image_bytes) >= max_refs:
                            break
                    except Exception as e:
                        logger.error("[Agent ImageGen] Failed to convert image '%s': %s", name, e)

        # Import API service
        try:
            from mixar.modules.common.api import get_imagegen_service
        except ImportError as e:
            self.report({"ERROR"}, f"ImageGen API service not available: {e}")
            return {"CANCELLED"}

        service = get_imagegen_service()

        # Set generating flag
        scene.mixie_imagegen_is_generating = True
        scene.mixie_imagegen_error = ""
        start_progress('imagegen')

        # Store values for callback
        stored_prompt = prompt
        stored_add_to_moodboard = self.add_to_moodboard

        def on_success(response):
            """Handle successful generation response."""
            logger.debug("[Agent ImageGen] Generation complete")

            try:
                if not response.success:
                    error_msg = getattr(response, "error", None) or "Generation failed"
                    reset_progress('imagegen')
                    scene.mixie_imagegen_is_generating = False
                    scene.mixie_imagegen_error = f"API Error: {error_msg}"
                    logger.error("[Agent ImageGen] %s", error_msg)
                    return

                data = response.data
                if not data:
                    reset_progress('imagegen')
                    scene.mixie_imagegen_is_generating = False
                    scene.mixie_imagegen_error = "No data received"
                    logger.error("[Agent ImageGen] No data received")
                    return

                # Check for failure status
                if isinstance(data, dict):
                    status = data.get("status", "").lower()
                    if status in ("failure", "error"):
                        error_message = data.get("message", "Unknown error")
                        reset_progress('imagegen')
                        scene.mixie_imagegen_is_generating = False
                        scene.mixie_imagegen_error = error_message
                        logger.error("[Agent ImageGen] %s", error_message)
                        return

                    # Handle nested data structure
                    if "data" in data and isinstance(data["data"], dict):
                        data = data["data"]

                # Extract job handle (backend request_id) for artifact tagging.
                # Used by the agent's list_moodboard_images / list_recent_3d_imports
                # tools to correlate moodboard items back to the producing job.
                job_handle = data.get("request_id", "") if isinstance(data, dict) else ""
                job_handle = job_handle or ""

                # Extract images from response
                images = []
                if isinstance(data, dict):
                    images_list = data.get("images", [])
                    for img_item in images_list:
                        if isinstance(img_item, dict) and "url" in img_item:
                            images.append(img_item["url"])
                        elif isinstance(img_item, str):
                            images.append(img_item)

                    if not images:
                        single_url = data.get("image_url")
                        if single_url:
                            images.append(single_url)

                if not images:
                    reset_progress('imagegen')
                    scene.mixie_imagegen_is_generating = False
                    scene.mixie_imagegen_error = "No images in response"
                    logger.error("[Agent ImageGen] No images in response")
                    return

                logger.debug("[Agent ImageGen] Received %s image(s)", len(images))

                # Download and optionally add to moodboard
                added_count = 0
                for i, image_url in enumerate(images):
                    try:
                        timestamp = int(time.time())
                        name = f"agent_imagegen_{timestamp}_{i}"
                        img = load_image_from_url(image_url, name)

                        if stored_add_to_moodboard:
                            add_image_to_moodboard(img, stored_prompt, job_handle=job_handle)

                        added_count += 1
                        logger.debug("[Agent ImageGen] Added image: %s", img.name)
                    except Exception as e:
                        logger.error("[Agent ImageGen] Failed to download image %s: %s", i, e)

                complete_progress('imagegen')
                scene.mixie_imagegen_is_generating = False
                scene.mixie_imagegen_error = ""

                # Redraw UI
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == "MIXIE":
                            area.tag_redraw()

                logger.debug("[Agent ImageGen] Successfully generated %s image(s)", added_count)

            except Exception as e:
                logger.error("[Agent ImageGen] %s", e, exc_info=True)
                reset_progress('imagegen')
                scene.mixie_imagegen_is_generating = False
                scene.mixie_imagegen_error = str(e)

        def on_error(error):
            """Handle generation error."""
            error_str = str(error) if error else "Unknown error"
            reset_progress('imagegen')
            scene.mixie_imagegen_is_generating = False
            scene.mixie_imagegen_error = error_str
            logger.error("[Agent ImageGen] %s", error_str)

        def on_complete(async_response):
            """Handle completion."""
            if scene.mixie_imagegen_is_generating:
                error = getattr(async_response, "error", None)
                response = getattr(async_response, "response", None)

                if error:
                    reset_progress('imagegen')
                    scene.mixie_imagegen_is_generating = False
                    scene.mixie_imagegen_error = str(error)
                elif response and not response.success:
                    error_msg = getattr(response, "error", None)
                    if not error_msg and response.data:
                        error_msg = response.data.get("message", "Unknown error")
                    reset_progress('imagegen')
                    scene.mixie_imagegen_is_generating = False
                    scene.mixie_imagegen_error = error_msg or "Unknown error"
                else:
                    scene.mixie_imagegen_is_generating = False

                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == "MIXIE":
                            area.tag_redraw()

        # Call API
        try:
            # Build kwargs based on model
            kwargs = {
                "prompt": prompt,
                "model": model,
                "style": self.style,
                "aspect_ratio": self.aspect_ratio,
                "number_of_images": self.number_of_images,
                "on_success": on_success,
                "on_error": on_error,
                "on_complete": on_complete,
            }

            # Add negative prompt if provided
            if self.negative_prompt and self.negative_prompt.strip():
                kwargs["negative_prompt"] = self.negative_prompt.strip()

            # Add resolution for pro model
            if model == "pro":
                kwargs["resolution"] = self.resolution

            # Add reference images if any
            if reference_image_bytes:
                kwargs["reference_images"] = reference_image_bytes

            service.generate_async(**kwargs)

        except Exception as e:
            scene.mixie_imagegen_is_generating = False
            reset_progress('imagegen')
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Image generation started...")
        return {"FINISHED"}


classes = (
    MIXIE_OT_agent_imagegen,
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
