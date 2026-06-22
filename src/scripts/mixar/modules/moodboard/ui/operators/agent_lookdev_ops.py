# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent Lookdev Operator

Simplified operator for agent-driven Lookdev (depth-to-image) generation.
Takes all parameters as properties for direct invocation.
"""

import time

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from mixar.modules.common.utils.image_utils import (
    add_image_to_moodboard,
    load_image_from_url,
    load_image_from_base64,
    IMAGE_BASE_SIZE,
    IMAGE_SPACING,
)
from mixar.modules.moodboard.core.moodboard_utils import get_moodboard_viewport_center
from ...core.generate_progress import start_progress, reset_progress, complete_progress


class MIXIE_OT_agent_lookdev(Operator):
    """Generate images from depth map using AI for agent use"""

    bl_idname = "mixie.agent_lookdev"
    bl_label = "Agent Lookdev Generate"
    bl_description = "Generate images from scene depth via agent"
    bl_options = {"REGISTER"}

    # Required
    prompt: bpy.props.StringProperty(
        name="Prompt",
        description="Text description for the generated image",
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

        prompt = self.prompt.strip()

        # Render depth map from scene
        try:
            from mixar.modules.moodboard.core.lookdev_utils import prepare_depth_render
            depth_filepath, success = prepare_depth_render()

            if not success or not depth_filepath:
                self.report(
                    {"ERROR"},
                    "Failed to render depth map. Ensure there is a camera in the scene.",
                )
                return {"CANCELLED"}

            from mixar.modules.common.utils.image_utils import compress_file_for_upload
            depth_bytes = compress_file_for_upload(depth_filepath)

            logger.debug("[Agent Lookdev] Rendered depth map from scene")
        except Exception as e:
            self.report({"ERROR"}, f"Failed to render depth map: {e}")
            return {"CANCELLED"}

        # Import API service
        try:
            from mixar.modules.common.api import get_lookdev_service
        except ImportError as e:
            self.report({"ERROR"}, f"Lookdev API service not available: {e}")
            return {"CANCELLED"}

        service = get_lookdev_service()

        # Set generating flag
        scene.mixie_lookdev_is_generating = True
        start_progress('lookdev')

        # Store values for callback
        stored_prompt = prompt
        stored_add_to_moodboard = self.add_to_moodboard

        def on_success(response):
            """Handle successful generation response."""
            logger.debug("[Agent Lookdev] Generation complete")

            try:
                if not response.success:
                    error_msg = getattr(response, "error", None) or "Generation failed"
                    reset_progress('lookdev')
                    scene.mixie_lookdev_is_generating = False
                    logger.error("[Agent Lookdev] %s", error_msg)
                    return

                data = response.data
                if not data:
                    reset_progress('lookdev')
                    scene.mixie_lookdev_is_generating = False
                    logger.error("[Agent Lookdev] No data received")
                    return

                # Check for failure status
                if isinstance(data, dict):
                    status = data.get("status", "").lower()
                    if status in ("failure", "error"):
                        error_message = data.get("message", "Unknown error")
                        reset_progress('lookdev')
                        scene.mixie_lookdev_is_generating = False
                        logger.error("[Agent Lookdev] %s", error_message)
                        return

                    # Handle nested data structure
                    if "data" in data and isinstance(data["data"], dict):
                        data = data["data"]

                        # Check for failure in inner data
                        if data.get("status", "").lower() in ("failure", "error"):
                            error_message = data.get("message", "Unknown error")
                            reset_progress('lookdev')
                            scene.mixie_lookdev_is_generating = False
                            logger.error("[Agent Lookdev] %s", error_message)
                            return

                # Extract job handle (backend request_id) for artifact tagging.
                job_handle = data.get("request_id", "") if isinstance(data, dict) else ""
                job_handle = job_handle or ""

                # Extract images from response
                image_urls = _extract_image_urls(data)

                if not image_urls:
                    reset_progress('lookdev')
                    scene.mixie_lookdev_is_generating = False
                    logger.error("[Agent Lookdev] No images in response")
                    return

                logger.debug("[Agent Lookdev] Received %s image(s)", len(image_urls))

                # Download and optionally add to moodboard
                added_count = 0
                viewport_cx, viewport_cy = get_moodboard_viewport_center()
                for i, url_or_data in enumerate(image_urls):
                    try:
                        timestamp = int(time.time())
                        name = f"agent_lookdev_{timestamp}_{i}"

                        if url_or_data.startswith("http"):
                            img = load_image_from_url(url_or_data, name)
                        else:
                            img = load_image_from_base64(url_or_data, name)

                        if stored_add_to_moodboard:
                            pos_x = viewport_cx + i * (IMAGE_BASE_SIZE + IMAGE_SPACING)
                            add_image_to_moodboard(
                                img, stored_prompt,
                                position_x=pos_x, position_y=viewport_cy,
                                job_handle=job_handle,
                            )

                        added_count += 1
                        logger.debug("[Agent Lookdev] Added image: %s", img.name)
                    except Exception as e:
                        logger.error("[Agent Lookdev] Failed to download image %s: %s", i, e)

                complete_progress('lookdev')
                scene.mixie_lookdev_is_generating = False

                # Redraw UI
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == "MIXIE":
                            area.tag_redraw()

                logger.debug("[Agent Lookdev] Successfully generated %s image(s)", added_count)

            except Exception as e:
                logger.error("[Agent Lookdev] %s", e, exc_info=True)
                reset_progress('lookdev')
                scene.mixie_lookdev_is_generating = False

        def on_error(error):
            """Handle generation error."""
            error_str = str(error) if error else "Unknown error"
            reset_progress('lookdev')
            scene.mixie_lookdev_is_generating = False
            logger.error("[Agent Lookdev] %s", error_str)

        def on_complete(async_response):
            """Handle completion."""
            if scene.mixie_lookdev_is_generating:
                error = getattr(async_response, "error", None)
                response = getattr(async_response, "response", None)

                if error:
                    reset_progress('lookdev')
                    scene.mixie_lookdev_is_generating = False
                elif response and not response.success:
                    error_msg = getattr(response, "error", None)
                    if not error_msg and response.data:
                        error_msg = response.data.get("message", "Unknown error")
                    reset_progress('lookdev')
                    scene.mixie_lookdev_is_generating = False
                else:
                    scene.mixie_lookdev_is_generating = False

                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == "MIXIE":
                            area.tag_redraw()

        # Call API
        try:
            service.generate_async(
                depth_map=depth_bytes,
                prompt=prompt,
                on_success=on_success,
                on_error=on_error,
                on_complete=on_complete,
            )
        except Exception as e:
            scene.mixie_lookdev_is_generating = False
            reset_progress('lookdev')
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Lookdev generation started...")
        return {"FINISHED"}


def _extract_image_urls(data: dict) -> list[str]:
    """Extract image URLs from various API response formats."""
    urls = []

    if not isinstance(data, dict):
        return urls

    # Check for images array (new API format)
    if "images" in data and isinstance(data["images"], list):
        for img_item in data["images"]:
            if isinstance(img_item, dict) and "url" in img_item:
                urls.append(img_item["url"])
            elif isinstance(img_item, str):
                urls.append(img_item)

    # Check for image_urls array (old API format)
    if not urls and "image_urls" in data:
        urls.extend(data["image_urls"])

    # Check for single image
    if not urls and "image" in data and isinstance(data["image"], str):
        urls.append(data["image"])

    # Check for single url
    if not urls and "url" in data and isinstance(data["url"], str):
        urls.append(data["url"])

    return urls


classes = (MIXIE_OT_agent_lookdev,)
