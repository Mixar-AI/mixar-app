# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev Scene Operators

Operator for generating lookdev images from a 3D viewport depth render.
"""

import bpy
from bpy.types import Operator
import time

from ...core.lookdev_utils import prepare_depth_render
from mixar.modules.common.utils.image_utils import (
    load_image_from_base64,
    load_image_from_url,
    add_image_to_moodboard,
    IMAGE_BASE_SIZE,
    IMAGE_SPACING,
)
from mixar.modules.common.utils.mixie_space_utils import show_generation_error, redraw_mixie_areas
from mixar.modules.moodboard.core.moodboard_utils import get_moodboard_viewport_center
from ...core.generate_progress import start_progress, complete_progress, reset_progress
from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def _get_lookdev_props(scene):
    """Get lookdev tab properties from sidebar, with fallback to old properties."""
    if hasattr(scene, 'mixie_moodboard_sidebar') and scene.mixie_moodboard_sidebar:
        sidebar = scene.mixie_moodboard_sidebar
        if hasattr(sidebar, 'tab_lookdev'):
            return sidebar.tab_lookdev
    return None


class MIXIE_OT_lookdev_generate_from_scene(Operator):
    """Render depth map from scene and generate lookdev images"""

    bl_idname = "mixie.lookdev_generate_from_scene"
    bl_label = "Generate from Scene"
    bl_description = "Render depth map from current scene and generate AI images using Flux Depth"
    bl_options = {'REGISTER'}

    from_chat: bpy.props.BoolProperty(
        name="From Chat",
        description="Called from chat context - use global scene property for prompt",
        default=False,
    )

    def execute(self, context):
        scene = context.scene

        # Get lookdev tab properties from sidebar
        props = _get_lookdev_props(scene)

        # When called from chat, skip sidebar prompt entirely — use the
        # global property that the chat handler set so the user's chat
        # prompt is never overridden by stale sidebar text.
        if self.from_chat:
            prompt = getattr(scene, 'mixie_lookdev_prompt', '')
        elif props:
            prompt = props.prompt
            # If sidebar prompt is empty, try global property as fallback
            if not prompt or not prompt.strip():
                fallback = getattr(scene, 'mixie_lookdev_prompt', '')
                if fallback and fallback.strip():
                    logger.debug("[Lookdev from Scene] Sidebar prompt empty, using fallback = '%s'", fallback)
                    prompt = fallback
        else:
            # Fallback to old properties
            prompt = getattr(scene, 'mixie_lookdev_prompt', '')

        logger.debug("[Lookdev from Scene] Final prompt value = '%s'", prompt)

        if not prompt or not prompt.strip():
            self.report({'WARNING'}, "Please enter a prompt")
            return {'CANCELLED'}

        # Set generating flag
        if hasattr(scene, 'mixie_lookdev_is_generating'):
            scene.mixie_lookdev_is_generating = True
        start_progress('lookdev')

        # Render depth map from scene
        fast_mode = props.fast_mode if props else False
        mode_str = " (fast mode)" if fast_mode else ""
        self.report({'INFO'}, f"Rendering depth map from scene{mode_str}...")
        depth_filepath, success = prepare_depth_render(fast_mode=fast_mode)

        if not success or not depth_filepath:
            if hasattr(scene, 'mixie_lookdev_is_generating'):
                scene.mixie_lookdev_is_generating = False
            reset_progress('lookdev')
            self.report({'ERROR'}, "Failed to render depth map")
            return {'CANCELLED'}

        # Load depth map into Blender (but don't add to moodboard)
        try:
            depth_image = bpy.data.images.load(depth_filepath, check_existing=False)
            depth_image.name = f"depth_{int(time.time())}"
            depth_image.pack()
            logger.debug("[Lookdev] Loaded depth map: %s", depth_image.name)
        except Exception as e:
            if hasattr(scene, 'mixie_lookdev_is_generating'):
                scene.mixie_lookdev_is_generating = False
            reset_progress('lookdev')
            self.report({'ERROR'}, f"Failed to load depth map: {e}")
            return {'CANCELLED'}

        # Read depth map file as bytes for API
        try:
            from mixar.modules.common.utils.image_utils import compress_file_for_service
            depth_bytes = compress_file_for_service(depth_filepath, "lookdev")
            logger.debug("[Lookdev] Compressed depth map to %d bytes", len(depth_bytes))
        except Exception as e:
            if hasattr(scene, 'mixie_lookdev_is_generating'):
                scene.mixie_lookdev_is_generating = False
            reset_progress('lookdev')
            self.report({'ERROR'}, f"Failed to read depth map: {e}")
            return {'CANCELLED'}

        # Import lookdev service
        try:
            from mixar.modules.common.api import get_lookdev_service
        except ImportError as e:
            if hasattr(scene, 'mixie_lookdev_is_generating'):
                scene.mixie_lookdev_is_generating = False
            self.report({'ERROR'}, f"Lookdev API service not available: {e}")
            return {'CANCELLED'}

        service = get_lookdev_service()

        # Clear previous error
        if hasattr(scene, 'mixie_lookdev_error'):
            scene.mixie_lookdev_error = ""

        # Store prompt for callback
        stored_prompt = prompt

        # Start offset for generated images: place at viewport centre
        _viewport_cx, _viewport_cy = get_moodboard_viewport_center()
        START_OFFSET = _viewport_cx
        START_OFFSET_Y = _viewport_cy

        def show_error(message: str):
            show_generation_error(
                scene, "Lookdev", message,
                "mixie_lookdev_is_generating", "mixie_lookdev_error",
            )

        def on_success(response):
            """Handle successful generation response."""
            # Bail out if user cancelled
            if not getattr(scene, 'mixie_lookdev_is_generating', False):
                logger.info("[Lookdev] Generation cancelled, ignoring response")
                return

            logger.debug("[Lookdev] on_success called")
            logger.debug("[Lookdev] response.success: %s", response.success)

            try:
                if not response.success:
                    error_msg = getattr(response, 'error', None) or "Generation failed"
                    show_error(f"API Error: {error_msg}")
                    return

                data = response.data
                if not data:
                    show_error("No data received from server")
                    return

                # Check for failure status
                if isinstance(data, dict):
                    status = data.get('status', '').lower()
                    if status in ('failure', 'error'):
                        error_message = data.get('message', 'Unknown error')
                        show_error(f"Server Error: {error_message}")
                        return

                    # Check for nested data structure
                    if 'data' in data and isinstance(data['data'], dict):
                        inner_data = data['data']
                        if inner_data.get('status', '').lower() in ('failure', 'error'):
                            error_message = inner_data.get('message', 'Unknown error')
                            show_error(f"Server Error: {error_message}")
                            return

                        # New API format: images array with url objects
                        if 'images' in inner_data and isinstance(inner_data['images'], list):
                            images = inner_data['images']
                            logger.debug("[Lookdev] Found %d images in inner data", len(images))
                            for i, img_item in enumerate(images):
                                try:
                                    name = f"lookdev_{int(time.time())}_{i}"
                                    if isinstance(img_item, dict) and 'url' in img_item:
                                        img = load_image_from_url(img_item['url'], name)
                                    elif isinstance(img_item, str):
                                        if img_item.startswith('http'):
                                            img = load_image_from_url(img_item, name)
                                        else:
                                            img = load_image_from_base64(img_item, name)
                                    else:
                                        continue
                                    pos_x = START_OFFSET + i * (IMAGE_BASE_SIZE + IMAGE_SPACING)
                                    add_image_to_moodboard(img, stored_prompt, position_x=pos_x, position_y=START_OFFSET_Y)
                                    logger.debug("[Lookdev] Added image at x=%s", pos_x)
                                except Exception as e:
                                    show_error(f"Failed to download image {i}: {e}")
                                    return
                            bpy.ops.ed.undo_push(message="Blockout to Render")
                            if hasattr(scene, 'mixie_lookdev_is_generating'):
                                scene.mixie_lookdev_is_generating = False
                            complete_progress('lookdev')
                            redraw_mixie_areas()
                            return

                        # Old API format: image_urls array of strings
                        if 'image_urls' in inner_data:
                            urls = inner_data['image_urls']
                            logger.debug("[Lookdev] Found %d image URLs", len(urls))
                            for i, url in enumerate(urls):
                                try:
                                    name = f"lookdev_{int(time.time())}_{i}"
                                    img = load_image_from_url(url, name)
                                    pos_x = START_OFFSET + i * (IMAGE_BASE_SIZE + IMAGE_SPACING)
                                    add_image_to_moodboard(img, stored_prompt, position_x=pos_x, position_y=START_OFFSET_Y)
                                    logger.debug("[Lookdev] Added image at x=%s", pos_x)
                                except Exception as e:
                                    show_error(f"Failed to download image {i}: {e}")
                                    return
                            bpy.ops.ed.undo_push(message="Blockout to Render")
                            if hasattr(scene, 'mixie_lookdev_is_generating'):
                                scene.mixie_lookdev_is_generating = False
                            complete_progress('lookdev')
                            redraw_mixie_areas()
                            return

                    # Check for image_urls at top level
                    if 'image_urls' in data:
                        urls = data['image_urls']
                        logger.debug("[Lookdev] Found %d image URLs at top level", len(urls))
                        for i, url in enumerate(urls):
                            try:
                                name = f"lookdev_{int(time.time())}_{i}"
                                img = load_image_from_url(url, name)
                                pos_x = START_OFFSET + i * (IMAGE_BASE_SIZE + IMAGE_SPACING)
                                add_image_to_moodboard(img, stored_prompt, position_x=pos_x, position_y=START_OFFSET_Y)
                                logger.debug("[Lookdev] Added image at x=%s", pos_x)
                            except Exception as e:
                                show_error(f"Failed to download image {i}: {e}")
                                return
                        bpy.ops.ed.undo_push(message="Blockout to Render")
                        if hasattr(scene, 'mixie_lookdev_is_generating'):
                            scene.mixie_lookdev_is_generating = False
                        complete_progress('lookdev')
                        redraw_mixie_areas()
                        return

                    # Handle single image
                    if 'image' in data:
                        img_data = data['image']
                        if isinstance(img_data, str):
                            try:
                                image_name = f"lookdev_{int(time.time())}"
                                if img_data.startswith('http'):
                                    img = load_image_from_url(img_data, image_name)
                                else:
                                    img = load_image_from_base64(img_data, image_name)
                                add_image_to_moodboard(img, stored_prompt, position_x=START_OFFSET, position_y=START_OFFSET_Y)
                            except Exception as e:
                                show_error(f"Failed to load image: {e}")
                                return
                        bpy.ops.ed.undo_push(message="Blockout to Render")
                        if hasattr(scene, 'mixie_lookdev_is_generating'):
                            scene.mixie_lookdev_is_generating = False
                        complete_progress('lookdev')
                        redraw_mixie_areas()
                        return

                    if 'url' in data:
                        try:
                            image_name = f"lookdev_{int(time.time())}"
                            img = load_image_from_url(data['url'], image_name)
                            add_image_to_moodboard(img, stored_prompt, position_x=START_OFFSET, position_y=START_OFFSET_Y)
                        except Exception as e:
                            show_error(f"Failed to download image: {e}")
                            return
                        bpy.ops.ed.undo_push(message="Blockout to Render")
                        if hasattr(scene, 'mixie_lookdev_is_generating'):
                            scene.mixie_lookdev_is_generating = False
                        complete_progress('lookdev')
                        redraw_mixie_areas()
                        return

                    if 'images' in data and isinstance(data['images'], list):
                        for i, img_item in enumerate(data['images']):
                            name = f"lookdev_{int(time.time())}_{i}"
                            try:
                                if isinstance(img_item, str):
                                    if img_item.startswith('http'):
                                        img = load_image_from_url(img_item, name)
                                    else:
                                        img = load_image_from_base64(img_item, name)
                                elif isinstance(img_item, dict):
                                    if 'url' in img_item:
                                        img = load_image_from_url(img_item['url'], name)
                                    elif 'data' in img_item:
                                        img = load_image_from_base64(img_item['data'], name)
                                    else:
                                        continue
                                else:
                                    continue

                                if img:
                                    pos_x = START_OFFSET + i * (IMAGE_BASE_SIZE + IMAGE_SPACING)
                                    add_image_to_moodboard(img, stored_prompt, position_x=pos_x, position_y=START_OFFSET_Y)
                            except Exception as e:
                                show_error(f"Failed to load image {i}: {e}")
                                return
                        bpy.ops.ed.undo_push(message="Blockout to Render")
                        if hasattr(scene, 'mixie_lookdev_is_generating'):
                            scene.mixie_lookdev_is_generating = False
                        complete_progress('lookdev')
                        redraw_mixie_areas()
                        return

                    show_error(f"No recognized image format. Keys: {list(data.keys())}")

            except Exception as e:
                logger.exception("[Lookdev] Error processing response")
                show_error(f"Error processing response: {e}")

        def on_error(error):
            """Handle generation error."""
            if not getattr(scene, 'mixie_lookdev_is_generating', False):
                return
            logger.debug("[Lookdev] on_error called with: %s", error)
            error_str = str(error) if error else "Unknown error"
            show_error(f"Request failed: {error_str}")

        def on_complete(async_response):
            """Handle completion (called regardless of success/failure)."""
            logger.debug("[Lookdev] on_complete called")

            is_generating = getattr(scene, 'mixie_lookdev_is_generating', False)
            if is_generating:
                error = getattr(async_response, 'error', None)
                response = getattr(async_response, 'response', None)

                if error:
                    show_error(f"Request failed: {error}")
                elif response and not response.success:
                    error_msg = getattr(response, 'error', None)
                    if not error_msg and response.data:
                        error_msg = response.data.get('message', 'Unknown error')
                    show_error(f"Server error: {error_msg or 'Unknown error'}")
                else:
                    if hasattr(scene, 'mixie_lookdev_is_generating'):
                        scene.mixie_lookdev_is_generating = False
                    complete_progress('lookdev')
                    redraw_mixie_areas()

        # Call async API
        try:
            service.generate_async(
                depth_map=depth_bytes,
                prompt=prompt.strip(),
                on_success=on_success,
                on_error=on_error,
                on_complete=on_complete,
            )
        except Exception as e:
            if hasattr(scene, 'mixie_lookdev_is_generating'):
                scene.mixie_lookdev_is_generating = False
            reset_progress('lookdev')
            self.report({'ERROR'}, f"Failed to start generation: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, "Depth map rendered, generation started...")
        return {'FINISHED'}


classes = (
    MIXIE_OT_lookdev_generate_from_scene,
)

