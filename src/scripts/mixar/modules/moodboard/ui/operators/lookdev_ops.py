# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev Operators

Operators for generating images from depth maps using the Lookdev API.
"""

import bpy
from bpy.types import Operator
import time

from mixar.modules.common.utils.image_utils import (
    compress_image_for_upload,
    load_image_from_base64,
    load_image_from_url,
    add_image_to_moodboard,
    IMAGE_BASE_SIZE,
    IMAGE_SPACING,
)
from mixar.modules.common.utils.mixie_space_utils import show_generation_error
from mixar.modules.moodboard.core.moodboard_utils import get_moodboard_viewport_center
from mixar.config.logging_config import get_logger
from ....common.utils.file_select_utils import file_select_guard, mark_file_select_executed
from ...core.generate_progress import start_progress, complete_progress, reset_progress

logger = get_logger(__name__)


def _get_lookdev_props(scene):
    """Get lookdev tab properties from sidebar, with fallback to old properties."""
    if hasattr(scene, 'mixie_moodboard_sidebar') and scene.mixie_moodboard_sidebar:
        sidebar = scene.mixie_moodboard_sidebar
        if hasattr(sidebar, 'tab_lookdev'):
            return sidebar.tab_lookdev
    return None


class MIXIE_OT_lookdev_generate(Operator):
    """Generate an image from a depth map using the Lookdev API (Flux Depth)"""

    bl_idname = "mixie.lookdev_generate"
    bl_label = "Generate Lookdev"
    bl_description = "Generate an image from a depth map using Flux Depth AI model"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene

        # Get lookdev tab properties from sidebar
        props = _get_lookdev_props(scene)

        # Debug logging to diagnose prompt reading issue
        logger.debug("Checking sidebar properties...")
        logger.debug("hasattr(scene, 'mixie_moodboard_sidebar') = %s",
                      hasattr(scene, 'mixie_moodboard_sidebar'))
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            sidebar = scene.mixie_moodboard_sidebar
            logger.debug("sidebar = %s", sidebar)
            logger.debug("hasattr(sidebar, 'tab_lookdev') = %s",
                          hasattr(sidebar, 'tab_lookdev'))
            if hasattr(sidebar, 'tab_lookdev'):
                tab = sidebar.tab_lookdev
                logger.debug("tab_lookdev = %s", tab)
                logger.debug("tab_lookdev.prompt = '%s'", tab.prompt)

        if props:
            logger.debug("Using props.prompt = '%s'", props.prompt)
            prompt = props.prompt
            # If sidebar prompt is empty, try global property as fallback
            if not prompt or not prompt.strip():
                fallback = getattr(scene, 'mixie_lookdev_prompt', '')
                if fallback and fallback.strip():
                    logger.debug("Sidebar prompt empty, using fallback = '%s'", fallback)
                    prompt = fallback
        else:
            # Fallback to old properties
            prompt = getattr(scene, 'mixie_lookdev_prompt', '')
            logger.debug("Using fallback prompt = '%s'", prompt)

        logger.debug("Final prompt value = '%s' (empty=%s)", prompt, not prompt)

        if not prompt or not prompt.strip():
            self.report({'WARNING'}, "Please enter a prompt (press Enter to confirm your text)")
            return {'CANCELLED'}

        # Always render depth from the 3D scene — Blockout to Render
        # does not use moodboard images as depth maps.
        return bpy.ops.mixie.lookdev_generate_from_scene()

        # Convert image to PNG bytes
        try:
            depth_bytes = compress_image_for_upload(depth_image)
            logger.debug("Converted image to %s bytes", len(depth_bytes))
        except Exception as e:
            self.report({'ERROR'}, f"Failed to convert image: {e}")
            return {'CANCELLED'}

        # Import lookdev service
        try:
            from mixar.modules.common.api import get_lookdev_service
        except ImportError as e:
            self.report({'ERROR'}, f"Lookdev API service not available: {e}")
            return {'CANCELLED'}

        service = get_lookdev_service()

        # Set generating flag and clear previous error
        if hasattr(scene, 'mixie_lookdev_is_generating'):
            scene.mixie_lookdev_is_generating = True
        if hasattr(scene, 'mixie_lookdev_error'):
            scene.mixie_lookdev_error = ""
        start_progress('lookdev')
        _completed = False

        # Store prompt for callback
        stored_prompt = prompt

        def show_error(message: str):
            show_generation_error(
                scene, "Lookdev", message,
                "mixie_lookdev_is_generating", "mixie_lookdev_error",
            )

        def on_success(response):
            """Handle successful generation response."""
            nonlocal _completed
            _completed = True
            logger.debug("on_success called")
            logger.debug("response.success: %s", response.success)
            logger.debug("response.error: %s", getattr(response, 'error', None))

            try:
                # Check response.success flag
                if not response.success:
                    error_msg = getattr(response, 'error', None) or "Generation failed"
                    show_error(f"API Error: {error_msg}")
                    return

                data = response.data
                logger.debug("response.data: %s", data)

                if not data:
                    show_error("No data received from server")
                    return

                # Check for failure status in response data
                if isinstance(data, dict):
                    status = data.get('status', '').lower()
                    if status == 'failure' or status == 'error':
                        error_message = data.get('message', 'Unknown error from server')
                        show_error(f"Server Error: {error_message}")
                        return

                # Capture viewport centre once so all images land near it
                viewport_cx, viewport_cy = get_moodboard_viewport_center()

                # Handle different response formats
                image_name = f"lookdev_{int(time.time())}"

                if isinstance(data, dict):
                    logger.debug("Data keys: %s", data.keys())

                    # Check for nested data structure (status/message/data pattern)
                    if 'data' in data and isinstance(data['data'], dict):
                        inner_data = data['data']
                        # Check for failure in inner data
                        if inner_data.get('status', '').lower() in ('failure', 'error'):
                            error_message = inner_data.get('message', 'Unknown error')
                            show_error(f"Server Error: {error_message}")
                            return

                        # New API format: images array with url objects
                        if 'images' in inner_data and isinstance(inner_data['images'], list):
                            images = inner_data['images']
                            logger.debug("Found %s images in inner data", len(images))
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
                                    pos_x = viewport_cx + i * (IMAGE_BASE_SIZE + IMAGE_SPACING)
                                    add_image_to_moodboard(
                                        img, stored_prompt,
                                        position_x=pos_x, position_y=viewport_cy,
                                    )
                                    logger.info("Added generated image: %s at x=%s", img.name, pos_x)
                                except Exception as e:
                                    show_error(f"Failed to download image {i}: {e}")
                                    return
                            scene.mixie_lookdev_is_generating = False
                            complete_progress('lookdev')
                            return

                        # Old API format: image_urls array of strings
                        if 'image_urls' in inner_data:
                            urls = inner_data['image_urls']
                            logger.debug("Found %s image URLs", len(urls))
                            for i, url in enumerate(urls):
                                try:
                                    name = f"lookdev_{int(time.time())}_{i}"
                                    img = load_image_from_url(url, name)
                                    pos_x = viewport_cx + i * (IMAGE_BASE_SIZE + IMAGE_SPACING)
                                    add_image_to_moodboard(
                                        img, stored_prompt,
                                        position_x=pos_x, position_y=viewport_cy,
                                    )
                                    logger.info("Added generated image: %s at x=%s", img.name, pos_x)
                                except Exception as e:
                                    show_error(f"Failed to download image {i}: {e}")
                                    return
                            scene.mixie_lookdev_is_generating = False
                            complete_progress('lookdev')
                            return

                    # Check for image_urls at top level
                    if 'image_urls' in data:
                        urls = data['image_urls']
                        logger.debug("Found %s image URLs at top level", len(urls))
                        for i, url in enumerate(urls):
                            try:
                                name = f"lookdev_{int(time.time())}_{i}"
                                img = load_image_from_url(url, name)
                                pos_x = viewport_cx + i * (IMAGE_BASE_SIZE + IMAGE_SPACING)
                                add_image_to_moodboard(
                                    img, stored_prompt,
                                    position_x=pos_x, position_y=viewport_cy,
                                )
                                logger.info("Added generated image: %s at x=%s", img.name, pos_x)
                            except Exception as e:
                                show_error(f"Failed to download image {i}: {e}")
                                return
                        scene.mixie_lookdev_is_generating = False
                        complete_progress('lookdev')
                        return

                    # Check for base64 image data
                    if 'image' in data:
                        img_data = data['image']
                        if isinstance(img_data, str):
                            try:
                                if img_data.startswith('http'):
                                    img = load_image_from_url(img_data, image_name)
                                else:
                                    img = load_image_from_base64(img_data, image_name)
                                add_image_to_moodboard(img, stored_prompt)
                                logger.info("Added generated image: %s", img.name)
                            except Exception as e:
                                show_error(f"Failed to load image: {e}")
                                return
                        scene.mixie_lookdev_is_generating = False
                        complete_progress('lookdev')
                        return

                    if 'url' in data:
                        try:
                            img = load_image_from_url(data['url'], image_name)
                            add_image_to_moodboard(img, stored_prompt)
                            logger.info("Added generated image from URL: %s", img.name)
                        except Exception as e:
                            show_error(f"Failed to download image: {e}")
                            return
                        scene.mixie_lookdev_is_generating = False
                        complete_progress('lookdev')
                        return

                    if 'images' in data and isinstance(data['images'], list):
                        for i, img_item in enumerate(data['images']):
                            name = f"lookdev_{int(time.time())}_{i}"
                            img = None
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
                                if img:
                                    pos_x = viewport_cx + i * (IMAGE_BASE_SIZE + IMAGE_SPACING)
                                    add_image_to_moodboard(
                                        img, stored_prompt,
                                        position_x=pos_x, position_y=viewport_cy,
                                    )
                                    logger.info("Added generated image: %s at x=%s", img.name, pos_x)
                            except Exception as e:
                                show_error(f"Failed to load image {i}: {e}")
                                return
                        scene.mixie_lookdev_is_generating = False
                        complete_progress('lookdev')
                        return

                    show_error(f"No recognized image format in response. Keys: {list(data.keys())}")
                else:
                    show_error(f"Unexpected response format: {type(data)}")

            except Exception as e:
                logger.error("Error processing response: %s", e, exc_info=True)
                show_error(f"Error processing response: {e}")

        def on_error(error):
            """Handle generation error."""
            nonlocal _completed
            _completed = True
            logger.error("on_error called with: %s", error)
            error_str = str(error) if error else "Unknown error"
            reset_progress('lookdev')
            show_error(f"Request failed: {error_str}")

        def on_complete(async_response):
            """Handle completion (called regardless of success/failure)."""
            logger.debug("on_complete called")
            logger.debug("async_response status: %s", getattr(async_response, 'status', 'unknown'))

            # If we reach here and neither on_success nor on_error fired, something went wrong
            if not _completed:
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
                    logger.debug("on_complete: Resetting generating state")
                    if hasattr(scene, 'mixie_lookdev_is_generating'):
                        scene.mixie_lookdev_is_generating = False
                    complete_progress('lookdev')
                    for area in bpy.context.screen.areas:
                        if area.type == 'MIXIE':
                            area.tag_redraw()

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

        self.report({'INFO'}, "Lookdev generation started...")
        return {'FINISHED'}


class MIXIE_OT_lookdev_pick_depth_image(Operator):
    """Pick a depth map image file"""

    bl_idname = "mixie.lookdev_pick_depth_image"
    bl_label = "Pick Depth Map"
    bl_description = "Select a depth map image file"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to the depth map image file",
        subtype='FILE_PATH'
    )

    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tiff;*.webp;*.exr",
        options={'HIDDEN'}
    )

    def invoke(self, context, event):
        if not file_select_guard(self, context):
            return {'FINISHED'}
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        import os

        if not self.filepath:
            self.report({'WARNING'}, "No file selected")
            return {'CANCELLED'}

        # Validate path
        try:
            filepath = os.path.abspath(os.path.realpath(self.filepath))
        except (OSError, ValueError) as e:
            self.report({'ERROR'}, f"Invalid file path: {e}")
            return {'CANCELLED'}

        if not os.path.isfile(filepath):
            self.report({'ERROR'}, f"File not found: {filepath}")
            return {'CANCELLED'}

        # Load the image
        try:
            img = bpy.data.images.load(filepath, check_existing=True)
            img.pack()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load image: {e}")
            return {'CANCELLED'}

        # Set as depth image
        context.scene.mixie_lookdev_depth_image = img

        self.report({'INFO'}, f"Selected '{img.name}' as depth map")
        mark_file_select_executed(self)
        return {'FINISHED'}


classes = (
    MIXIE_OT_lookdev_generate,
    MIXIE_OT_lookdev_pick_depth_image,
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
