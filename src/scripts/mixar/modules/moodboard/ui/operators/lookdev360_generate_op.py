# SPDX-FileCopyrightText: 2025 Blender Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev 360 Generate Operator

Main operator for generating PBR textures from 3D objects using the Lookdev 360 API.
Handles the full pipeline: validation, UV check, MPaint setup, OBJ export, async API
call, texture download, and fill layer creation in the paint module.
"""

import bpy
from bpy.types import Operator
import time
import os

from mixar.config.logging_config import get_logger

from ...core.lookdev360_utils import (
    save_material_checkpoint,
    ensure_uv_unwrap,
    export_objects_to_obj,
    download_texture_from_url,
    get_selected_mesh_objects,
)
from ...core.lookdev360_paint_integration import (
    check_or_create_mpaint_setup,
    add_lookdev360_fill_layer,
)
from mixar.modules.common.utils.image_utils import compress_for_service
from mixar.modules.moodboard.core.generate_progress import (
    start_progress, complete_progress, reset_progress,
)

logger = get_logger(__name__)


def _get_lookdev360_props(scene):
    """Get lookdev360 tab properties from sidebar."""
    if hasattr(scene, 'mixie_moodboard_sidebar') and scene.mixie_moodboard_sidebar:
        sidebar = scene.mixie_moodboard_sidebar
        if hasattr(sidebar, 'tab_lookdev360'):
            return sidebar.tab_lookdev360
    return None


class MIXIE_OT_lookdev360_generate(Operator):
    """Generate PBR textures from selected objects using AI"""

    bl_idname = "mixie.lookdev360_generate"
    bl_label = "Generate Lookdev 360"
    bl_description = "Generate PBR textures for selected objects using AI"
    bl_options = {'REGISTER'}

    from_chat: bpy.props.BoolProperty(
        name="From Chat",
        description="Called from chat context - use global scene property for prompt",
        default=False,
    )

    def execute(self, context):
        scene = context.scene

        # Get lookdev360 tab properties from sidebar
        props = _get_lookdev360_props(scene)

        # When called from chat, skip sidebar prompt entirely — use the
        # global property that the chat handler set so the user's chat
        # prompt is never overridden by stale sidebar text.
        if self.from_chat:
            prompt = getattr(scene, 'mixie_lookdev360_prompt', '')
            reference_image = None
        elif props:
            prompt = props.prompt
            reference_image = props.reference_image
            # If sidebar prompt is empty, try global property as fallback
            if not prompt or not prompt.strip():
                fallback = getattr(scene, 'mixie_lookdev360_prompt', '')
                if fallback and fallback.strip():
                    prompt = fallback
        else:
            # Fallback to old properties
            prompt = getattr(scene, 'mixie_lookdev360_prompt', '')
            reference_image = None

        # Validate prompt
        if not prompt or not prompt.strip():
            self.report({'WARNING'}, "Please enter a prompt (press Enter to confirm your text)")
            return {'CANCELLED'}

        # Get selected mesh objects
        mesh_objects = get_selected_mesh_objects()
        if not mesh_objects:
            self.report({'WARNING'}, "No mesh objects selected")
            return {'CANCELLED'}

        # Step 1: Save material checkpoint
        checkpoint = save_material_checkpoint(mesh_objects)
        if hasattr(scene, 'mixie_lookdev360_checkpoint'):
            scene.mixie_lookdev360_checkpoint = checkpoint

        # Step 2: Ensure UV unwrap on all objects
        for obj in mesh_objects:
            if not ensure_uv_unwrap(obj):
                self.report({'WARNING'}, f"Failed to create UV map for '{obj.name}'")
                return {'CANCELLED'}

        # Step 2b: Ensure MPaint (ucupaint) setup exists on each object
        for obj in mesh_objects:
            node = check_or_create_mpaint_setup(obj)
            if not node:
                self.report({'WARNING'}, f"Failed to create paint setup for '{obj.name}'")
                return {'CANCELLED'}

        # Step 3: Export to OBJ
        obj_path, success = export_objects_to_obj(mesh_objects)
        if not success or not obj_path:
            self.report({'ERROR'}, "Failed to export OBJ file")
            return {'CANCELLED'}

        # Step 3b: Check exported file size (backend limit is 50MB)
        try:
            file_size = os.path.getsize(obj_path)
            max_size = 50 * 1024 * 1024  # 50MB
            if file_size > max_size:
                size_mb = file_size / (1024 * 1024)
                self.report({'ERROR'}, f"Exported mesh is too large ({size_mb:.1f} MB). Maximum size is 50 MB")
                try:
                    os.unlink(obj_path)
                except OSError:
                    pass
                return {'CANCELLED'}
        except OSError as e:
            logger.warning("Could not check file size: %s", e)

        # Step 4: Get image bytes if provided, routed by style_only flag
        style_image_bytes = None
        reference_image_bytes = None
        if reference_image:
            try:
                img_bytes = compress_for_service(reference_image, "lookdev360")
                style_only = getattr(props, 'style_only', False)
                if style_only:
                    style_image_bytes = img_bytes
                else:
                    reference_image_bytes = img_bytes
            except Exception as e:
                logger.error("Failed to convert image: %s", e)

        # Step 4b: Get resolution setting
        resolution = None
        if props:
            res_str = getattr(props, 'resolution', '1024')
            try:
                resolution = int(res_str)
            except (ValueError, TypeError):
                resolution = 1024

        # Step 5: Import lookdev 360 service
        try:
            from mixar.modules.common.api import get_lookdev_360_service
        except ImportError as e:
            self.report({'ERROR'}, f"Lookdev 360 API service not available: {e}")
            try:
                os.unlink(obj_path)
            except OSError:
                pass
            return {'CANCELLED'}

        service = get_lookdev_360_service()

        # Set generating flag and clear any previous error
        start_progress('lookdev360')
        if hasattr(scene, 'mixie_lookdev360_is_generating'):
            scene.mixie_lookdev360_is_generating = True
        if hasattr(scene, 'mixie_lookdev360_error'):
            scene.mixie_lookdev360_error = ""

        # Store references for callback closures
        stored_objects = [obj.name for obj in mesh_objects]
        stored_obj_path = obj_path
        stored_props = props

        def show_error(message: str):
            """Show error message to user via popup and store in scene property."""
            logger.error("%s", message)
            reset_progress('lookdev360')
            if hasattr(scene, 'mixie_lookdev360_is_generating'):
                scene.mixie_lookdev360_is_generating = False
            if hasattr(scene, 'mixie_lookdev360_error'):
                scene.mixie_lookdev360_error = message

            try:
                if stored_obj_path and os.path.exists(stored_obj_path):
                    os.unlink(stored_obj_path)
            except OSError:
                pass

            for area in bpy.context.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()

            def draw_error(self, context):
                self.layout.label(text=message)

            bpy.context.window_manager.popup_menu(
                draw_error, title="Lookdev 360 Error", icon='ERROR'
            )

        def on_success(response):
            """Handle successful generation response."""
            # Bail out if user cancelled
            if not getattr(scene, 'mixie_lookdev360_is_generating', False):
                logger.info("[Lookdev360] Generation cancelled, ignoring response")
                return

            try:
                if not response.success:
                    error_msg = getattr(response, 'error', None) or "Generation failed"
                    show_error(f"API Error: {error_msg}")
                    return

                data = response.data
                if not data:
                    show_error("No data received from server")
                    return

                if isinstance(data, dict):
                    status = data.get('status', '').lower()
                    if status in ('failure', 'error'):
                        show_error(f"Server Error: {data.get('message', 'Unknown error')}")
                        return

                # Extract texture URLs from response
                albedo_url, roughness_url, metallic_url, normal_url = (
                    _extract_texture_urls(data)
                )

                if not albedo_url:
                    show_error("Missing BaseColor texture URL in server response")
                    return

                # Download textures
                timestamp = int(time.time())
                albedo_img, roughness_img, metallic_img, normal_img = (
                    _download_textures(
                        albedo_url, roughness_url, metallic_url,
                        normal_url, timestamp, show_error,
                    )
                )
                if not albedo_img:
                    return  # show_error already called

                # Apply textures as fill layers via paint module
                _apply_as_fill_layers(
                    stored_objects, albedo_img, roughness_img,
                    metallic_img, normal_img, timestamp,
                    scene, stored_props, stored_obj_path, show_error,
                )

                # Push an undo step so the node-tree changes can be
                # safely undone (the async callback runs outside any
                # operator undo context).
                bpy.ops.ed.undo_push(message="Lookdev 360: Apply PBR Textures")

            except Exception as e:
                logger.error("Error processing response: %s", e, exc_info=True)
                show_error(f"Error processing response: {e}")

        def on_error(error):
            """Handle generation error."""
            if not getattr(scene, 'mixie_lookdev360_is_generating', False):
                return
            show_error(f"Request failed: {error or 'Unknown error'}")

        def on_complete(async_response):
            """Handle completion (safety net)."""
            is_generating = getattr(scene, 'mixie_lookdev360_is_generating', False)
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
                    if hasattr(scene, 'mixie_lookdev360_is_generating'):
                        scene.mixie_lookdev360_is_generating = False
                    for area in bpy.context.screen.areas:
                        if area.type == 'MIXIE':
                            area.tag_redraw()

        # Step 6: Call async API
        try:
            service.generate_async(
                mesh_file=obj_path,
                prompt=prompt.strip(),
                style_ref_image=style_image_bytes,
                reference_image=reference_image_bytes,
                resolution=resolution,
                on_success=on_success,
                on_error=on_error,
                on_complete=on_complete,
            )
        except Exception as e:
            reset_progress('lookdev360')
            if hasattr(scene, 'mixie_lookdev360_is_generating'):
                scene.mixie_lookdev360_is_generating = False
            self.report({'ERROR'}, f"Failed to start generation: {e}")
            try:
                os.unlink(obj_path)
            except OSError:
                pass
            return {'CANCELLED'}

        self.report({'INFO'}, "Lookdev 360 generation started...")
        return {'FINISHED'}


def _extract_texture_urls(data):
    """Extract texture URLs from API response data.

    Returns:
        Tuple of (albedo_url, roughness_url, metallic_url, normal_url)
    """
    albedo_url = roughness_url = metallic_url = normal_url = None

    if not isinstance(data, dict):
        return albedo_url, roughness_url, metallic_url, normal_url

    inner_data = data
    if 'data' in data and isinstance(data['data'], dict):
        inner_data = data['data']

    if 'textures' in inner_data and isinstance(inner_data['textures'], list):
        for tex in inner_data['textures']:
            if not isinstance(tex, dict):
                continue
            tex_type = tex.get('texture_type', '').lower()
            url = tex.get('url', '')
            if tex_type == 'basecolor' and url:
                albedo_url = url
            elif tex_type == 'roughness' and url:
                roughness_url = url
            elif tex_type == 'metallic' and url:
                metallic_url = url
            elif tex_type == 'normal' and url:
                normal_url = url

    return albedo_url, roughness_url, metallic_url, normal_url


def _download_textures(
    albedo_url, roughness_url, metallic_url, normal_url, timestamp, show_error
):
    """Download PBR textures from URLs.

    Returns:
        Tuple of (albedo_img, roughness_img, metallic_img, normal_img)
    """
    try:
        albedo_img = download_texture_from_url(
            albedo_url, f"pbr_basecolor_{timestamp}"
        )
    except Exception as e:
        show_error(f"Failed to download BaseColor texture: {e}")
        return None, None, None, None

    roughness_img = None
    if roughness_url:
        try:
            roughness_img = download_texture_from_url(
                roughness_url, f"pbr_roughness_{timestamp}"
            )
        except Exception as e:
            logger.warning("Failed to download Roughness texture: %s", e)

    metallic_img = None
    if metallic_url:
        try:
            metallic_img = download_texture_from_url(
                metallic_url, f"pbr_metallic_{timestamp}"
            )
        except Exception as e:
            logger.warning("Failed to download Metallic texture: %s", e)

    normal_img = None
    if normal_url:
        try:
            normal_img = download_texture_from_url(
                normal_url, f"pbr_normal_{timestamp}"
            )
        except Exception as e:
            logger.warning("Failed to download Normal texture: %s", e)

    return albedo_img, roughness_img, metallic_img, normal_img


def _apply_as_fill_layers(
    stored_objects, albedo_img, roughness_img, metallic_img, normal_img,
    timestamp, scene, stored_props, stored_obj_path, show_error,
):
    """Apply downloaded textures as fill layers in the paint module."""
    from mixar.modules.paint.core.node.node_utils import get_active_mpaint_node

    layer_name = f"PBR_{timestamp}"
    applied_count = 0

    for obj_name in stored_objects:
        obj = bpy.data.objects.get(obj_name)
        if not obj:
            continue

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        node = get_active_mpaint_node(obj)
        if not node or not node.node_tree:
            logger.warning("No MPaint node for '%s', skipping", obj_name)
            continue

        group_tree = node.node_tree
        mp = group_tree.mp

        layer = add_lookdev360_fill_layer(
            mp=mp,
            group_tree=group_tree,
            albedo_img=albedo_img,
            roughness_img=roughness_img,
            metallic_img=metallic_img,
            normal_img=normal_img,
            layer_name=layer_name,
        )
        if layer:
            applied_count += 1

    if applied_count == 0:
        show_error("Failed to apply textures to any object")
        return

    bpy.ops.file.pack_all()

    # Store layer name for restore functionality
    if hasattr(scene, 'mixie_lookdev360_layer_name'):
        scene.mixie_lookdev360_layer_name = layer_name
    if stored_props and hasattr(stored_props, 'layer_name'):
        stored_props.layer_name = layer_name

    # Set flags
    complete_progress('lookdev360')
    if hasattr(scene, 'mixie_lookdev360_is_generating'):
        scene.mixie_lookdev360_is_generating = False
    if hasattr(scene, 'mixie_lookdev360_has_applied'):
        scene.mixie_lookdev360_has_applied = True
    if stored_props and hasattr(stored_props, 'has_applied_materials'):
        stored_props.has_applied_materials = True

    # Clean up temp OBJ
    try:
        if stored_obj_path and os.path.exists(stored_obj_path):
            os.unlink(stored_obj_path)
    except OSError:
        pass

    # Redraw UI
    for area in bpy.context.screen.areas:
        if area.type == 'MIXIE':
            area.tag_redraw()

    def draw_success(self, context):
        self.layout.label(text="Textures generated and applied as fill layer!")

    bpy.context.window_manager.popup_menu(
        draw_success, title="Lookdev 360", icon='CHECKMARK'
    )


classes = (
    MIXIE_OT_lookdev360_generate,
)
