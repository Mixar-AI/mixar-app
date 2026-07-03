# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent Lookdev 360 Operator

Simplified operator for agent-driven Lookdev 360 PBR texture generation.
Takes all parameters as properties for direct invocation.
"""

import os
import time

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.generate_progress import start_progress, reset_progress, complete_progress
from mixar.modules.moodboard.core.lookdev360_utils import (
    get_selected_mesh_objects,
    save_material_checkpoint,
    ensure_uv_unwrap,
    export_objects_to_obj,
    download_texture_from_url,
)
from mixar.modules.moodboard.core.lookdev360_paint_integration import (
    check_or_create_mpaint_setup,
    add_lookdev360_fill_layer,
)


class MIXIE_OT_agent_lookdev360(Operator):
    """Generate PBR textures for selected mesh objects via agent"""

    bl_idname = "mixie.agent_lookdev360"
    bl_label = "Agent Lookdev 360"
    bl_description = "Generate PBR textures for selected mesh objects via agent"
    bl_options = {"REGISTER"}

    # Required
    prompt: bpy.props.StringProperty(
        name="Prompt",
        description="Text description for the generated textures",
        default="",
    )

    # Optional style reference image
    reference_image_name: bpy.props.StringProperty(
        name="Reference Image",
        description="Optional image name in bpy.data.images to use as style reference",
        default="",
    )

    def execute(self, context):
        scene = context.scene

        # Validate prompt
        if not self.prompt or not self.prompt.strip():
            self.report({"ERROR"}, "Prompt is required")
            return {"CANCELLED"}

        prompt = self.prompt.strip()

        # Get selected mesh objects
        mesh_objects = get_selected_mesh_objects()

        if not mesh_objects:
            self.report(
                {"ERROR"},
                "No mesh objects selected. Select mesh objects in the 3D viewport first.",
            )
            return {"CANCELLED"}

        object_names = [obj.name for obj in mesh_objects]
        logger.debug("[Agent Lookdev360] Processing %s mesh object(s)", len(mesh_objects))

        # Save material checkpoint for undo
        checkpoint = save_material_checkpoint(mesh_objects)
        logger.debug("[Agent Lookdev360] Material checkpoint saved")

        # Ensure UV unwrap on all objects
        for obj in mesh_objects:
            if not ensure_uv_unwrap(obj):
                self.report({"ERROR"}, f"Failed to create UV map for '{obj.name}'")
                return {"CANCELLED"}

        # Ensure MPaint (ucupaint) setup exists on each object
        for obj in mesh_objects:
            node = check_or_create_mpaint_setup(obj)
            if not node:
                self.report({"ERROR"}, f"Failed to create paint setup for '{obj.name}'")
                return {"CANCELLED"}

        # Export to OBJ
        obj_path, success = export_objects_to_obj(mesh_objects)
        if not success or not obj_path:
            self.report({"ERROR"}, "Failed to export OBJ file")
            return {"CANCELLED"}

        # Check exported file size (backend limit is 50MB)
        try:
            file_size = os.path.getsize(obj_path)
            max_size = 50 * 1024 * 1024  # 50MB
            if file_size > max_size:
                size_mb = file_size / (1024 * 1024)
                self.report({"ERROR"}, f"Exported mesh is too large ({size_mb:.1f} MB). Maximum size is 50 MB")
                try:
                    os.unlink(obj_path)
                except OSError:
                    pass
                return {"CANCELLED"}
        except OSError as e:
            logger.warning("[Agent Lookdev360] Could not check file size: %s", e)

        logger.debug("[Agent Lookdev360] Exported OBJ file")

        # Get reference image bytes if provided
        style_image_bytes = None
        if self.reference_image_name:
            img = bpy.data.images.get(self.reference_image_name)
            if img and img.has_data:
                try:
                    from mixar.modules.common.utils.image_utils import compress_image_for_upload
                    style_image_bytes = compress_image_for_upload(img)
                    logger.debug("[Agent Lookdev360] Using reference image: %s", self.reference_image_name)
                except Exception as e:
                    logger.warning("[Agent Lookdev360] Failed to convert reference image: %s", e)
            elif self.reference_image_name:
                logger.warning("[Agent Lookdev360] Reference image '%s' not found or has no data", self.reference_image_name)

        # Get the service
        try:
            from mixar.modules.common.api import get_lookdev_360_service
            service = get_lookdev_360_service()
        except ImportError as e:
            self.report({"ERROR"}, f"Lookdev 360 API service not available: {e}")
            # Clean up temp file
            try:
                os.unlink(obj_path)
            except OSError:
                pass
            return {"CANCELLED"}

        # Set generating flag
        scene.mixie_lookdev360_is_generating = True
        start_progress('lookdev360')

        # Store values for callbacks
        stored_obj_path = obj_path
        stored_object_names = object_names
        stored_checkpoint = checkpoint

        def cleanup_obj_file():
            """Clean up temporary OBJ file."""
            try:
                if os.path.exists(stored_obj_path):
                    os.unlink(stored_obj_path)
            except OSError:
                pass

        def on_success(response):
            """Handle successful generation response."""
            logger.debug("[Agent Lookdev360] Generation complete")

            try:
                if not response.success:
                    error_msg = getattr(response, "error", None) or "Generation failed"
                    reset_progress('lookdev360')
                    scene.mixie_lookdev360_is_generating = False
                    logger.error("[Agent Lookdev360] %s", error_msg)
                    cleanup_obj_file()
                    return

                data = response.data
                if not data:
                    reset_progress('lookdev360')
                    scene.mixie_lookdev360_is_generating = False
                    logger.error("[Agent Lookdev360] No data received from server")
                    cleanup_obj_file()
                    return

                # Check for failure status
                if isinstance(data, dict):
                    status = data.get("status", "").lower()
                    if status in ("failure", "error"):
                        error_message = data.get("message", "Unknown error from server")
                        reset_progress('lookdev360')
                        scene.mixie_lookdev360_is_generating = False
                        logger.error("[Agent Lookdev360] %s", error_message)
                        cleanup_obj_file()
                        return

                    # Handle nested data
                    if "data" in data and isinstance(data["data"], dict):
                        inner_data = data["data"]
                        if inner_data.get("status", "").lower() in ("failure", "error"):
                            error_message = inner_data.get("message", "Unknown error")
                            reset_progress('lookdev360')
                            scene.mixie_lookdev360_is_generating = False
                            logger.error("[Agent Lookdev360] %s", error_message)
                            cleanup_obj_file()
                            return
                        data = inner_data

                # Extract job handle (backend request_id) for artifact tagging.
                # Stamped on the downloaded PBR image datablocks (albedo,
                # roughness, etc.) so they can be correlated to the producing
                # job. Note: lookdev360 results land in a paint-layer node tree
                # rather than the moodboard, so we tag the source images
                # rather than a moodboard entry.
                job_handle = data.get("request_id", "") if isinstance(data, dict) else ""
                job_handle = job_handle or ""

                # Extract texture URLs
                albedo_url = None
                roughness_url = None
                metallic_url = None
                normal_url = None

                if isinstance(data, dict) and "textures" in data:
                    for tex in data.get("textures", []):
                        if isinstance(tex, dict):
                            tex_type = tex.get("texture_type", "").lower()
                            url = tex.get("url", "")
                            if tex_type == "basecolor" and url:
                                albedo_url = url
                            elif tex_type == "roughness" and url:
                                roughness_url = url
                            elif tex_type == "metallic" and url:
                                metallic_url = url
                            elif tex_type == "normal" and url:
                                normal_url = url

                if not albedo_url:
                    reset_progress('lookdev360')
                    scene.mixie_lookdev360_is_generating = False
                    logger.error("[Agent Lookdev360] Missing BaseColor texture URL in server response")
                    cleanup_obj_file()
                    return

                logger.debug("[Agent Lookdev360] Downloading textures...")

                # Download textures
                timestamp = int(time.time())

                try:
                    albedo_img = download_texture_from_url(
                        albedo_url, f"pbr_basecolor_{timestamp}"
                    )
                except Exception as e:
                    reset_progress('lookdev360')
                    scene.mixie_lookdev360_is_generating = False
                    logger.error("[Agent Lookdev360] Failed to download BaseColor texture: %s", e)
                    cleanup_obj_file()
                    return

                roughness_img = None
                if roughness_url:
                    try:
                        roughness_img = download_texture_from_url(
                            roughness_url, f"pbr_roughness_{timestamp}"
                        )
                    except Exception as e:
                        logger.warning("[Agent Lookdev360] Failed to download Roughness: %s", e)

                metallic_img = None
                if metallic_url:
                    try:
                        metallic_img = download_texture_from_url(
                            metallic_url, f"pbr_metallic_{timestamp}"
                        )
                    except Exception as e:
                        logger.warning("[Agent Lookdev360] Failed to download Metallic: %s", e)

                normal_img = None
                if normal_url:
                    try:
                        normal_img = download_texture_from_url(
                            normal_url, f"pbr_normal_{timestamp}"
                        )
                    except Exception as e:
                        logger.warning("[Agent Lookdev360] Failed to download Normal: %s", e)

                # Tag downloaded PBR images with the job handle so the agent
                # can trace each map back to its producing pipeline.
                if job_handle:
                    for img in (albedo_img, roughness_img, metallic_img, normal_img):
                        if img is not None:
                            img["mixar_job_handle"] = job_handle

                logger.debug("[Agent Lookdev360] Applying materials...")

                from mixar.modules.paint.core.node.node_utils import get_active_mpaint_node

                layer_name = f"PBR_{timestamp}"
                applied_count = 0

                for obj_name in stored_object_names:
                    obj = bpy.data.objects.get(obj_name)
                    if not obj:
                        continue

                    bpy.context.view_layer.objects.active = obj
                    obj.select_set(True)

                    node = get_active_mpaint_node(obj)
                    if not node or not node.node_tree:
                        logger.debug("[Agent Lookdev360] No MPaint node for '%s', skipping", obj_name)
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
                    reset_progress('lookdev360')
                    scene.mixie_lookdev360_is_generating = False
                    logger.error("[Agent Lookdev360] Original objects no longer exist")
                    cleanup_obj_file()
                    return

                bpy.ops.file.pack_all()

                complete_progress('lookdev360')
                scene.mixie_lookdev360_is_generating = False
                cleanup_obj_file()

                # Trigger UI redraw
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type in ("VIEW_3D", "MIXIE"):
                            area.tag_redraw()

            except Exception as e:
                logger.error("[Agent Lookdev360] %s", e, exc_info=True)
                reset_progress('lookdev360')
                scene.mixie_lookdev360_is_generating = False
                cleanup_obj_file()

        def on_error(error):
            """Handle generation error."""
            error_str = str(error) if error else "Unknown error"
            reset_progress('lookdev360')
            scene.mixie_lookdev360_is_generating = False
            logger.error("[Agent Lookdev360] %s", error_str)
            cleanup_obj_file()

        def on_complete(async_response):
            """Handle completion."""
            if scene.mixie_lookdev360_is_generating:
                error = getattr(async_response, "error", None)
                response = getattr(async_response, "response", None)

                if error:
                    reset_progress('lookdev360')
                    scene.mixie_lookdev360_is_generating = False
                elif response and not response.success:
                    error_msg = getattr(response, "error", None)
                    if not error_msg and response.data:
                        error_msg = response.data.get("message", "Unknown error")
                    reset_progress('lookdev360')
                    scene.mixie_lookdev360_is_generating = False
                else:
                    scene.mixie_lookdev360_is_generating = False

                cleanup_obj_file()

                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type in ("VIEW_3D", "MIXIE"):
                            area.tag_redraw()

        # Start async generation
        try:
            service.generate_async(
                mesh_file=obj_path,
                prompt=prompt,
                style_ref_image=style_image_bytes,
                on_success=on_success,
                on_error=on_error,
                on_complete=on_complete,
            )
        except Exception as e:
            scene.mixie_lookdev360_is_generating = False
            reset_progress('lookdev360')
            cleanup_obj_file()
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, "PBR texture generation started...")
        return {"FINISHED"}


classes = (MIXIE_OT_agent_lookdev360,)
