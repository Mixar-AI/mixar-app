# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image Gen Operators

Operators for AI image generation using the dynamic v2 API.
"""

import time

import bpy
from bpy.types import Operator

from mixar.modules.common.utils.image_utils import (
    add_image_to_moodboard,
    compress_for_service,
    load_image_from_url,
)
from mixar.modules.common.utils.mixie_space_utils import show_generation_error
from mixar.config.logging_config import get_logger
from ...core.generate_progress import start_progress, complete_progress, reset_progress

logger = get_logger(__name__)


def _get_max_refs(model_name: str) -> int:
    """Get maximum reference images for a model."""
    try:
        from mixar.bootstrap.imagegen_cache import get_max_reference_images

        return get_max_reference_images(model_name)
    except ImportError:
        # Fallback
        return 14 if model_name == "pro" else 3


class MIXIE_OT_imagegen_generate(Operator):
    """Generate images using AI and add them to the moodboard"""

    bl_idname = "mixie.imagegen_generate"
    bl_label = "Generate Image"
    bl_description = "Generate AI images and add them to the moodboard"
    bl_options = {"REGISTER"}

    from_chat: bpy.props.BoolProperty(
        name="From Chat",
        description="Called from chat context - use defaults",
        default=False,
    )

    def execute(self, context):
        scene = context.scene

        # Check if called from sidebar context - prefer sidebar properties
        use_sidebar_props = False
        sidebar_tab = None
        prompt = ""

        # When called from chat, skip sidebar prompt entirely — use the
        # global property that the chat handler set so the user's chat
        # prompt is never overridden by stale sidebar text.
        if self.from_chat:
            prompt = getattr(scene, 'mixie_imagegen_prompt', '')
        else:
            if hasattr(scene, 'mixie_moodboard_sidebar'):
                sidebar = scene.mixie_moodboard_sidebar
                if sidebar and hasattr(sidebar, 'tab_imagegen'):
                    sidebar_tab = sidebar.tab_imagegen
                    if sidebar_tab:
                        # Sidebar tab found - use sidebar context for reference images
                        # regardless of whether prompt comes from sidebar or fallback
                        use_sidebar_props = True

                        # Try to read prompt from sidebar
                        sidebar_prompt = ""

                        # Method 1: Direct attribute access
                        try:
                            sidebar_prompt = sidebar_tab.prompt
                        except Exception as e:
                            logger.debug("Prompt read error (direct): %s", e)

                        # Method 2: RNA path resolution if method 1 failed
                        if not sidebar_prompt or not sidebar_prompt.strip():
                            try:
                                sidebar_prompt = scene.path_resolve(
                                    "mixie_moodboard_sidebar.tab_imagegen.prompt"
                                )
                            except Exception as e:
                                logger.debug("Prompt read error (path_resolve): %s", e)

                        # Method 3: getattr chain as fallback
                        if not sidebar_prompt or not sidebar_prompt.strip():
                            try:
                                sb = getattr(scene, 'mixie_moodboard_sidebar', None)
                                if sb:
                                    tab = getattr(sb, 'tab_imagegen', None)
                                    if tab:
                                        sidebar_prompt = getattr(tab, 'prompt', '')
                            except Exception as e:
                                logger.debug("Prompt read error (getattr): %s", e)

                        if sidebar_prompt and sidebar_prompt.strip():
                            prompt = sidebar_prompt

            # Fallback to global property if sidebar prompt is empty
            if not prompt or not prompt.strip():
                global_prompt = getattr(scene, 'mixie_imagegen_prompt', '')
                if global_prompt and global_prompt.strip():
                    prompt = global_prompt

        if not prompt or not prompt.strip():
            self.report({"WARNING"}, "Please enter a prompt (press Enter to confirm your text)")
            return {"CANCELLED"}

        # Determine model and other params based on context
        if self.from_chat:
            # Use default model from cache for chat context
            try:
                from mixar.bootstrap.imagegen_cache import get_default_model_name

                model = get_default_model_name()
                if not model:
                    self.report(
                        {"WARNING"}, "No models available - please wait for models to load"
                    )
                    return {"CANCELLED"}
            except ImportError:
                self.report({"WARNING"}, "Model cache not available")
                return {"CANCELLED"}

            # Check for chat-attached reference images
            reference_image_bytes = []
            for ref_item in scene.mixie_imagegen_ref_images:
                if ref_item.image:
                    try:
                        ref_bytes = compress_for_service(ref_item.image, "imagegen")
                        reference_image_bytes.append(ref_bytes)
                    except Exception as e:
                        logger.error("Error converting chat reference image '%s': %s",
                                     ref_item.image.name, e)
        else:
            # Get model from appropriate source (sidebar or global properties)
            if use_sidebar_props:
                model = sidebar_tab.model if hasattr(sidebar_tab, 'model') else ""
            else:
                model = scene.mixie_imagegen_model

            if model in ("LOADING", "ERROR", "NONE", ""):
                # Scene property has invalid value, try to use first cached model
                try:
                    from mixar.bootstrap.imagegen_cache import get_default_model_name
                    model = get_default_model_name()
                except ImportError:
                    pass

            if not model or model in ("LOADING", "ERROR", "NONE", ""):
                self.report(
                    {"WARNING"}, "Please wait for models to load or check connection"
                )
                return {"CANCELLED"}

            # Get max reference images for this model
            max_refs = _get_max_refs(model)

            # Collect reference images
            reference_image_bytes = []

            # Determine which reference images to use based on context
            if use_sidebar_props:
                # Sidebar context: check toggle state
                use_moodboard_selection = getattr(sidebar_tab, 'use_reference_images', False)

                if use_moodboard_selection:
                    # Toggle ON: use currently selected moodboard images (dynamic)
                    for item in scene.mixie_moodboard_images:
                        if item.selected and item.image:
                            try:
                                img_bytes = compress_for_service(item.image, "imagegen")
                                reference_image_bytes.append(img_bytes)
                                if len(reference_image_bytes) >= max_refs:
                                    break
                            except Exception as e:
                                logger.error("Error converting moodboard image '%s': %s",
                                             item.image.name, e)
                else:
                    # Toggle OFF: use uploaded images from reference_images collection
                    if hasattr(sidebar_tab, 'reference_images'):
                        for ref_item in sidebar_tab.reference_images:
                            # Prefer direct image pointer, fall back to index
                            img = getattr(ref_item, 'image', None)
                            if not img and ref_item.moodboard_index >= 0:
                                mb_images = scene.mixie_moodboard_images
                                if ref_item.moodboard_index < len(mb_images):
                                    img = mb_images[ref_item.moodboard_index].image
                            if img:
                                try:
                                    img_bytes = compress_for_service(img, "imagegen")
                                    reference_image_bytes.append(img_bytes)
                                    if len(reference_image_bytes) >= max_refs:
                                        break
                                except Exception as e:
                                    logger.error("Error converting reference image '%s': %s",
                                                 img.name, e)
            else:
                # Popup context: use reference image collection + selected moodboard images
                # Add reference images from collection
                for ref_item in scene.mixie_imagegen_ref_images:
                    if ref_item.image:
                        try:
                            ref_bytes = compress_for_service(ref_item.image, "imagegen")
                            reference_image_bytes.append(ref_bytes)
                            if len(reference_image_bytes) >= max_refs:
                                break
                        except Exception as e:
                            logger.error("Error getting reference image: %s", e)

                # Add selected moodboard images (up to remaining slots)
                try:
                    for item in scene.mixie_moodboard_images:
                        if item.selected and item.image:
                            img_bytes = compress_for_service(item.image, "imagegen")
                            reference_image_bytes.append(img_bytes)
                            if len(reference_image_bytes) >= max_refs:
                                break
                except Exception as e:
                    logger.error("Error getting reference images: %s", e)

        # Import API service
        try:
            from mixar.modules.common.api import get_imagegen_service
        except ImportError as e:
            self.report({"ERROR"}, f"ImageGen API service not available: {e}")
            return {"CANCELLED"}

        service = get_imagegen_service()

        # Set generating flag and clear previous error
        scene.mixie_imagegen_is_generating = True
        scene.mixie_imagegen_error = ""
        start_progress('imagegen')
        _completed = False

        # Store values for callback
        stored_prompt = prompt.strip()
        stored_num_images = getattr(scene, "mixie_imagegen_num_images", 1)

        def show_error(message: str):
            show_generation_error(
                scene, "Generate Image", message,
                "mixie_imagegen_is_generating", "mixie_imagegen_error",
            )

        def on_success(response):
            """Handle successful generation response."""
            nonlocal _completed
            _completed = True

            # Bail out if user cancelled
            if not getattr(scene, 'mixie_imagegen_is_generating', False):
                logger.info("ImageGen cancelled, ignoring response")
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

                # Check for failure status
                if isinstance(data, dict):
                    status = data.get("status", "").lower()
                    if status in ("failure", "error"):
                        error_message = data.get("message", "Unknown error from server")
                        show_error(f"Server Error: {error_message}")
                        return

                    # Handle nested data structure
                    if "data" in data and isinstance(data["data"], dict):
                        data = data["data"]

                # Extract images from response (v2 API returns array)
                images = []
                if isinstance(data, dict):
                    images_list = data.get("images", [])
                    for img_item in images_list:
                        if isinstance(img_item, dict) and "url" in img_item:
                            images.append(img_item["url"])
                        elif isinstance(img_item, str):
                            images.append(img_item)

                    # Fallback to single image_url if no images array
                    if not images:
                        single_url = data.get("image_url")
                        if single_url:
                            images.append(single_url)

                if not images:
                    show_error("No image URLs in server response")
                    return

                logger.info("Received %s image(s)", len(images))

                # Download and add images to moodboard
                added_count = 0
                for i, image_url in enumerate(images):
                    try:
                        timestamp = int(time.time())
                        name = f"imagegen_{timestamp}_{i}"
                        img = load_image_from_url(image_url, name)
                        add_image_to_moodboard(img, stored_prompt)
                        added_count += 1
                        logger.info("Added generated image: %s", img.name)
                    except Exception as e:
                        logger.error("Failed to download image %s: %s", i, e)

                scene.mixie_imagegen_is_generating = False
                complete_progress('imagegen')

                if added_count > 0:
                    bpy.ops.ed.undo_push(message="Generate Image")

                for area in bpy.context.screen.areas:
                    if area.type == "MIXIE":
                        area.tag_redraw()

                if added_count > 0:

                    def draw_success(self, context):
                        if added_count == 1:
                            self.layout.label(text="Image generated successfully!")
                        else:
                            self.layout.label(
                                text=f"{added_count} images generated successfully!"
                            )

                    bpy.context.window_manager.popup_menu(
                        draw_success, title="Generate Image", icon="CHECKMARK"
                    )
                else:
                    show_error("Failed to download generated images")

            except Exception as e:
                logger.error("Error processing response: %s", e, exc_info=True)
                show_error(f"Error processing response: {e}")

        def on_error(error):
            """Handle generation error."""
            nonlocal _completed
            _completed = True
            if not getattr(scene, 'mixie_imagegen_is_generating', False):
                return
            error_str = str(error) if error else "Unknown error"
            reset_progress('imagegen')
            show_error(f"Request failed: {error_str}")

        def on_complete(async_response):
            """Handle completion."""
            if not getattr(scene, 'mixie_imagegen_is_generating', False):
                return
            if not _completed:
                error = getattr(async_response, "error", None)
                response = getattr(async_response, "response", None)

                if error:
                    show_error(f"Request failed: {error}")
                elif response and not response.success:
                    error_msg = getattr(response, "error", None)
                    if not error_msg and response.data:
                        error_msg = response.data.get("message", "Unknown error")
                    show_error(f"Server error: {error_msg or 'Unknown error'}")
                else:
                    scene.mixie_imagegen_is_generating = False
                    complete_progress('imagegen')
                    for area in bpy.context.screen.areas:
                        if area.type == "MIXIE":
                            area.tag_redraw()

        # Call v2 async API
        try:
            if self.from_chat:
                # Chat context: send prompt, model, and any attached reference images
                service.generate_async(
                    prompt=stored_prompt,
                    model=model,
                    reference_images=reference_image_bytes if reference_image_bytes else None,
                    on_success=on_success,
                    on_error=on_error,
                    on_complete=on_complete,
                )
            else:
                # UI context: send all properties from appropriate source
                if use_sidebar_props:
                    # Get properties from sidebar tab
                    style = getattr(sidebar_tab, 'style', 'REALISTIC')
                    aspect_ratio = getattr(sidebar_tab, 'aspect_ratio', '1_1')
                    resolution = getattr(sidebar_tab, 'resolution', '1024')
                    negative_prompt = None  # Sidebar doesn't have negative prompt yet
                else:
                    # Get properties from global scene properties
                    style = scene.mixie_imagegen_style
                    aspect_ratio = scene.mixie_imagegen_aspect_ratio
                    resolution = getattr(scene, "mixie_imagegen_resolution", "1K")
                    negative_prompt = scene.mixie_imagegen_negative_prompt or None

                service.generate_async(
                    prompt=stored_prompt,
                    model=model,
                    style=style,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    number_of_images=stored_num_images,
                    negative_prompt=negative_prompt,
                    reference_images=reference_image_bytes if reference_image_bytes else None,
                    on_success=on_success,
                    on_error=on_error,
                    on_complete=on_complete,
                )
        except Exception as e:
            scene.mixie_imagegen_is_generating = False
            reset_progress('imagegen')
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Image generation started...")
        return {"FINISHED"}


classes = (
    MIXIE_OT_imagegen_generate,
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
