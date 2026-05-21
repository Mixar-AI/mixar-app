# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Brush texture generation operators.

This module contains operators for AI-powered brush texture generation.
Generated textures are added to the moodboard for review. Users can then
apply a selected moodboard image as the brush mask/alpha texture.
"""

import time

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...utils import get_mixar_ui
from ...vcol.brush_utils import activate_local_brush
from .brush_texture_ops import get_or_create_local_brush


def _apply_image_as_mask(image):
    """Apply a Blender image as the active brush's mask texture.

    For local brushes, applies directly. For linked brushes, creates a
    local "Mixar Generated Brush" with asset_mark() and activates it
    via bpy.ops.brush.asset_activate — the only pattern that reliably
    switches brushes in Blender 5.0.

    Args:
        image: bpy.types.Image to use as mask

    Returns:
        True if successful, False otherwise.
    """
    try:
        settings = bpy.context.tool_settings.image_paint
        brush = settings.brush
        if not brush:
            logger.error("[BrushGen] No active brush found")
            return False

        # Use Non-Color for mask textures (grayscale masks)
        if image.colorspace_settings.name != 'Non-Color':
            image.colorspace_settings.name = 'Non-Color'

        # Create texture with image
        tex_name = f"Mask_{image.name}"
        tex = bpy.data.textures.get(tex_name)
        if not tex:
            tex = bpy.data.textures.new(tex_name, type='IMAGE')
        tex.image = image

        # LOCAL brush — apply directly
        if not brush.library:
            if brush.mask_texture and not brush.mask_texture.image:
                brush.mask_texture = None

            if brush.mask_texture:
                brush.mask_texture.image = image
            else:
                brush.mask_texture = tex

            if brush.mask_texture_slot:
                brush.mask_texture_slot.mask_map_mode = 'VIEW_PLANE'

            logger.debug("[BrushGen] Applied mask texture '%s' to brush '%s'",
                         image.name, brush.name)
            return True

        # LINKED brush — create/reuse "Mixar Generated Brush"
        logger.debug("[BrushGen] Brush '%s' is linked, creating local brush", brush.name)

        local_brush = get_or_create_local_brush(brush)
        if not local_brush:
            logger.error("[BrushGen] Failed to create local brush")
            return False

        # Apply mask texture to local brush
        local_brush.mask_texture = tex
        if local_brush.mask_texture_slot:
            local_brush.mask_texture_slot.mask_map_mode = 'VIEW_PLANE'

        # Activate the local brush (the only way to switch in Blender 5.0)
        if activate_local_brush(local_brush.name):
            logger.debug("[BrushGen] Activated local brush '%s'", local_brush.name)
        else:
            # Fallback: try direct assignment
            settings.brush = local_brush
            logger.debug("[BrushGen] Fallback: set settings.brush directly")

        return True

    except Exception as e:
        logger.error("[BrushGen] Failed to apply mask texture: %s", e)
        return False


def _redraw_ui(_context=None):
    """Force UI redraw for all relevant areas.

    Uses window manager iteration instead of a captured operator context,
    making it safe to call from async callbacks where the original operator
    context has expired (dangling C pointer after execute returns FINISHED).
    """
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


def _get_ref_image_bytes(mixar_ui):
    """Get reference image bytes from the UI state, or None."""
    ref_name = mixar_ui.brush_gen_ref_image
    if not ref_name:
        return None

    image = bpy.data.images.get(ref_name)
    if not image:
        return None

    try:
        from mixar.modules.common.utils.image_utils import image_to_png_bytes
        return image_to_png_bytes(image)
    except Exception as e:
        logger.error("[BrushGen] Failed to convert reference image to bytes: %s", e)
        return None


class MGenerateBrushTexture(Operator):
    """Generate a brush texture using AI and add it to the moodboard"""
    bl_idname = "wm.m_generate_brush_texture"
    bl_label = "Generate Brush Texture"
    bl_description = "Generate a brush texture from text prompt using AI"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context, 'tool_settings'):
            return False
        settings = context.tool_settings.image_paint
        return settings is not None and settings.brush is not None

    def execute(self, context):
        mixar_ui = get_mixar_ui(context)
        if not mixar_ui:
            self.report({'ERROR'}, "UI state not available")
            return {'CANCELLED'}

        # Atomic check-and-set to prevent concurrent requests
        if mixar_ui.brush_gen_in_progress:
            self.report({'WARNING'}, "Brush texture generation is already in progress")
            return {'CANCELLED'}
        mixar_ui.brush_gen_in_progress = True

        # Get the prompt
        prompt = mixar_ui.brush_texture_prompt.strip()
        if not prompt:
            mixar_ui.brush_gen_in_progress = False
            self.report({'WARNING'}, "Please enter a prompt for the brush texture")
            return {'CANCELLED'}

        # Import brush service
        try:
            from mixar.modules.common.api.services import get_brush_service
        except ImportError as e:
            mixar_ui.brush_gen_in_progress = False
            self.report({'ERROR'}, f"Brush API service not available: {e}")
            return {'CANCELLED'}

        service = get_brush_service()

        # Read model and reference image from UI state
        model_name = mixar_ui.brush_gen_model
        reference_image = _get_ref_image_bytes(mixar_ui)

        # Set generating state
        mixar_ui.brush_gen_progress = 0.1
        mixar_ui.brush_gen_status = "Requesting texture from AI..."
        _redraw_ui(context)

        # Store prompt for callbacks
        stored_prompt = prompt

        def show_error(message: str):
            """Show error message and reset state."""
            logger.error("[BrushGen] %s", message)
            mixar_ui.brush_gen_in_progress = False
            mixar_ui.brush_gen_progress = 0.0
            mixar_ui.brush_gen_status = f"Error: {message}"
            _redraw_ui(context)

        def on_success(response):
            """Handle successful generation response."""
            logger.debug("[BrushGen] on_success called")

            try:
                if not response.success:
                    error_msg = getattr(response, 'error', None) or "Generation failed"
                    show_error(f"API Error: {error_msg}")
                    return

                data = response.data
                logger.debug("[BrushGen] Response data received")

                if not data:
                    show_error("No data received from server")
                    return

                # Check for failure status in response data
                if isinstance(data, dict):
                    status = data.get('status', '').lower()
                    if status in ('failure', 'error'):
                        error_message = data.get('message', 'Unknown error from server')
                        show_error(f"Server Error: {error_message}")
                        return

                # Extract image URL from response
                image_url = None

                if isinstance(data, dict):
                    if 'data' in data and isinstance(data['data'], dict):
                        inner_data = data['data']
                        if inner_data.get('status', '').lower() in ('failure', 'error'):
                            error_message = inner_data.get('message', 'Unknown error')
                            show_error(f"Server Error: {error_message}")
                            return
                        image_url = inner_data.get('image_url')
                    else:
                        image_url = data.get('image_url') or data.get('url')

                if not image_url:
                    show_error("No image URL in server response")
                    return

                logger.debug("[BrushGen] Found image URL")

                # Update progress
                mixar_ui.brush_gen_progress = 0.5
                mixar_ui.brush_gen_status = "Downloading texture..."
                _redraw_ui(context)

                from mixar.modules.common.utils.image_utils import (
                    load_image_from_url,
                    add_image_to_moodboard,
                )

                try:
                    timestamp = int(time.time())
                    name = f"brush_gen_{timestamp}"

                    mixar_ui.brush_gen_progress = 0.8
                    mixar_ui.brush_gen_status = "Adding to moodboard..."
                    _redraw_ui(context)

                    # Download, load, pack, cleanup temp file
                    image = load_image_from_url(image_url, name)

                    # Add to moodboard (tags MIXIE areas for redraw)
                    add_image_to_moodboard(image, stored_prompt)

                    mixar_ui.brush_gen_in_progress = False
                    mixar_ui.brush_gen_progress = 1.0
                    mixar_ui.brush_gen_status = "Added to moodboard!"
                    _redraw_ui(context)
                    logger.debug("[BrushGen] Generation complete - added to moodboard")

                except Exception as e:
                    show_error(f"Failed to download/apply image: {e}")
                    return

            except Exception as e:
                logger.error("[BrushGen] Error processing response: %s", e)
                show_error(f"Error processing response: {e}")

        def on_error(error):
            """Handle generation error."""
            logger.error("[BrushGen] on_error called with: %s", error)
            error_str = str(error) if error else "Unknown error"
            show_error(f"Request failed: {error_str}")

        def on_complete(async_response):
            """Handle completion (called regardless of success/failure)."""
            logger.debug("[BrushGen] on_complete called")

            # If still in generating state, something went wrong
            if mixar_ui.brush_gen_in_progress:
                error = getattr(async_response, 'error', None)
                if error:
                    show_error(f"Request failed: {error}")
                else:
                    mixar_ui.brush_gen_in_progress = False
                    _redraw_ui(context)

        # Call async API
        try:
            service.generate_async(
                prompt=stored_prompt,
                model_name=model_name,
                reference_image=reference_image,
                on_success=on_success,
                on_error=on_error,
                on_complete=on_complete,
            )
        except Exception as e:
            mixar_ui.brush_gen_in_progress = False
            mixar_ui.brush_gen_status = ""
            self.report({'ERROR'}, f"Failed to start generation: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, "Brush texture generation started...")
        return {'FINISHED'}


class MBrushGenClearReference(Operator):
    """Clear the reference image for brush texture generation"""
    bl_idname = "wm.m_brush_gen_clear_reference"
    bl_label = "Clear Reference"
    bl_description = "Remove the reference image from brush generation"
    bl_options = {'REGISTER'}

    def execute(self, context):
        mixar_ui = get_mixar_ui(context)
        if not mixar_ui:
            self.report({'ERROR'}, "UI state not available")
            return {'CANCELLED'}

        mixar_ui.brush_gen_ref_image = ""
        _redraw_ui(context)
        return {'FINISHED'}


class MApplyBrushSelectedImage(Operator):
    """Apply a selected moodboard image as the brush mask texture"""
    bl_idname = "wm.m_apply_brush_selected_image"
    bl_label = "Apply Selected Image"
    bl_description = "Apply the selected moodboard image as brush mask texture"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context, 'tool_settings'):
            return False
        settings = context.tool_settings.image_paint
        if not settings or not settings.brush:
            return False
        scene = context.scene
        if not hasattr(scene, 'mixie_moodboard_images'):
            return False
        return any(img.selected for img in scene.mixie_moodboard_images)

    def execute(self, context):
        from mixar.modules.moodboard.core.moodboard_utils import (
            get_selected_moodboard_image_objects,
        )

        images = get_selected_moodboard_image_objects(context)
        if not images:
            self.report({'WARNING'}, "No valid moodboard image selected")
            return {'CANCELLED'}

        image = images[0]
        if _apply_image_as_mask(image):
            _redraw_ui(context)
            self.report({'INFO'}, f"Applied '{image.name}' as brush mask texture")
            return {'FINISHED'}

        self.report({'ERROR'}, "Failed to apply image as brush mask")
        return {'CANCELLED'}


class MBrushGenRefreshModels(Operator):
    """Refresh the list of available brush generation models"""
    bl_idname = "wm.m_brush_gen_refresh_models"
    bl_label = "Refresh Models"
    bl_description = "Refresh the list of available models from the server"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            from mixar.bootstrap.imagegen_cache import refresh_imagegen_cache
            refresh_imagegen_cache()
            self.report({'INFO'}, "Refreshing models...")
        except ImportError:
            self.report({'ERROR'}, "ImageGen cache module not available")
            return {'CANCELLED'}
        return {'FINISHED'}


# Classes for registration
classes = (
    MGenerateBrushTexture,
    MBrushGenClearReference,
    MApplyBrushSelectedImage,
    MBrushGenRefreshModels,
)
