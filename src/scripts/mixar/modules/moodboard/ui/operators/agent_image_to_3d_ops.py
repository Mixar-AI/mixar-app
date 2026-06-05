# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent Image to 3D Operator

Simplified operator for agent-driven Image to 3D model generation.
Supports both Trellis and Rodin models with model-specific parameters.
Uses a generation ID to prevent duplicate model imports when a user
re-triggers generation before the previous request completes.
"""

import bpy
from bpy.types import Operator
from bpy.props import (
    StringProperty,
    IntProperty,
    FloatProperty,
    BoolProperty,
    EnumProperty,
)

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.generate_progress import start_progress, reset_progress, complete_progress
from mixar.modules.moodboard.core.image_to_3d_utils import (
    download_and_import_model,
    get_model_url_from_response,
    get_file_format_from_url,
)

# Monotonically increasing ID to track the "current" agent generation request.
# Callbacks from superseded requests compare their captured ID against this
# value and skip the import if they no longer match.
_current_agent_generation_id = 0


class MIXIE_OT_agent_image_to_3d(Operator):
    """Generate 3D model from image via agent"""

    bl_idname = "mixie.agent_image_to_3d"
    bl_label = "Agent Image to 3D"
    bl_description = "Generate 3D model from image via agent"
    bl_options = {"REGISTER"}

    # Required
    image_name: StringProperty(
        name="Image Name",
        description="Name of image in bpy.data.images",
        default="",
    )

    # Model selection
    model: StringProperty(
        name="Model",
        description="Model identifier: 'trellis-1' or 'rodin'",
        default="trellis-1",
    )

    # Optional prompt
    prompt: StringProperty(
        name="Prompt",
        description="Optional text prompt to guide 3D generation",
        default="",
    )

    # Trellis-specific parameters
    texture_size: IntProperty(
        name="Texture Size",
        description="Output texture resolution (512, 1024, 2048, 4096)",
        default=2048,
        min=512,
        max=4096,
    )

    mesh_simplify: FloatProperty(
        name="Mesh Simplify",
        description="Mesh simplification ratio (higher = simpler mesh)",
        default=0.9,
        min=0.0,
        max=1.0,
    )

    generate_normal: BoolProperty(
        name="Generate Normal",
        description="Generate normal map",
        default=True,
    )

    save_gaussian_ply: BoolProperty(
        name="Save Gaussian PLY",
        description="Save Gaussian splatting PLY file",
        default=False,
    )

    # Rodin-specific parameters
    quality: EnumProperty(
        name="Quality",
        description="Quality level for Rodin model",
        items=[
            ("high", "High", "High quality"),
            ("medium", "Medium", "Medium quality (default)"),
            ("low", "Low", "Low quality"),
            ("extra-low", "Extra Low", "Extra low quality"),
        ],
        default="medium",
    )

    geometry_file_format: EnumProperty(
        name="File Format",
        description="Output file format for Rodin model",
        items=[
            ("glb", "GLB", "GL Transmission Format Binary"),
            ("usdz", "USDZ", "Universal Scene Description"),
            ("fbx", "FBX", "Filmbox"),
            ("obj", "OBJ", "Wavefront OBJ"),
            ("stl", "STL", "Stereolithography"),
        ],
        default="glb",
    )

    material: EnumProperty(
        name="Material",
        description="Material type for Rodin model",
        items=[
            ("PBR", "PBR", "Physically Based Rendering materials"),
            ("Shaded", "Shaded", "Simple shaded materials"),
            ("All", "All", "All material types"),
        ],
        default="PBR",
    )

    def execute(self, context):
        scene = context.scene

        # Guard: prevent duplicate generation while one is already in progress
        if getattr(scene, 'mixie_image_to_3d_is_generating', False):
            self.report({"WARNING"}, "Generation already in progress")
            return {"CANCELLED"}

        # Validate image_name
        if not self.image_name or not self.image_name.strip():
            self.report({"ERROR"}, "image_name is required")
            return {"CANCELLED"}

        image_name = self.image_name.strip()

        # Get image from bpy.data.images
        img = bpy.data.images.get(image_name)
        if not img:
            self.report({"ERROR"}, f"Image '{image_name}' not found in bpy.data.images")
            return {"CANCELLED"}

        if not img.has_data:
            self.report({"ERROR"}, f"Image '{image_name}' has no pixel data")
            return {"CANCELLED"}

        # Validate model
        model = self.model.strip().lower() if self.model else "trellis-1"
        if model not in ("trellis-1", "rodin"):
            self.report({"ERROR"}, f"Invalid model '{model}'. Must be 'trellis-1' or 'rodin'")
            return {"CANCELLED"}

        logger.debug("[Agent Image to 3D] Processing image '%s' with model '%s'", image_name, model)

        # Convert image to bytes
        try:
            from mixar.modules.common.utils.image_utils import compress_image_for_upload
            image_bytes = compress_image_for_upload(img)
            logger.debug("[Agent Image to 3D] Converted image to bytes")
        except Exception as e:
            self.report({"ERROR"}, f"Failed to convert image to bytes: {e}")
            return {"CANCELLED"}

        # Get the service
        try:
            from mixar.modules.common.api import get_model_3d_gen_service
            service = get_model_3d_gen_service()
        except ImportError as e:
            self.report({"ERROR"}, f"Model 3D Gen API service not available: {e}")
            return {"CANCELLED"}

        # Build parameters based on model type
        parameters = {}
        if model == "trellis-1":
            parameters = {
                "texture_size": self.texture_size,
                "mesh_simplify": self.mesh_simplify,
                "generate_normal": self.generate_normal,
                "save_gaussian_ply": self.save_gaussian_ply,
            }
        else:  # rodin
            parameters = {
                "quality": self.quality,
                "geometry_file_format": self.geometry_file_format,
                "material": self.material,
            }

        # Get prompt
        prompt = self.prompt.strip() if self.prompt else None

        # Set generating flag
        scene.mixie_image_to_3d_is_generating = True
        start_progress('image_to_3d')

        # Increment generation ID so stale callbacks are ignored
        global _current_agent_generation_id
        _current_agent_generation_id += 1
        my_generation_id = _current_agent_generation_id

        # Store values for callbacks
        stored_model = model
        stored_file_format = self.geometry_file_format if model == "rodin" else "glb"

        def on_success(response):
            """Handle successful generation response."""
            # Skip if this callback belongs to a superseded generation
            if my_generation_id != _current_agent_generation_id:
                logger.info(
                    "[Agent Image to 3D] Ignoring stale response (id=%d, current=%d)",
                    my_generation_id, _current_agent_generation_id,
                )
                return

            logger.debug("[Agent Image to 3D] Generation complete")

            try:
                if not response.success:
                    error_msg = getattr(response, "error", None) or "Generation failed"
                    reset_progress('image_to_3d')
                    scene.mixie_image_to_3d_is_generating = False
                    logger.error("[Agent Image to 3D] %s", error_msg)
                    return

                data = response.data
                if not data:
                    reset_progress('image_to_3d')
                    scene.mixie_image_to_3d_is_generating = False
                    logger.error("[Agent Image to 3D] No data received from server")
                    return

                # Check for failure status
                if isinstance(data, dict):
                    status = data.get("status", "").lower()
                    if status in ("failure", "error"):
                        error_message = data.get("message", "Unknown error from server")
                        reset_progress('image_to_3d')
                        scene.mixie_image_to_3d_is_generating = False
                        logger.error("[Agent Image to 3D] %s", error_message)
                        return

                # Extract job handle (backend request_id) for artifact tagging.
                # Stamped on imported objects so the agent's list_recent_3d_imports
                # tool can correlate scene objects back to the producing job.
                job_handle = data.get("request_id", "") if isinstance(data, dict) else ""
                job_handle = job_handle or ""

                # Extract model URL
                model_url = get_model_url_from_response(data)
                if not model_url:
                    reset_progress('image_to_3d')
                    scene.mixie_image_to_3d_is_generating = False
                    logger.error("[Agent Image to 3D] No model URL in server response")
                    return

                logger.debug("[Agent Image to 3D] Downloading and importing 3D model...")

                # Determine file format from URL or use stored format
                file_format = get_file_format_from_url(model_url)
                if stored_model == "rodin":
                    file_format = stored_file_format

                # Download and import the model
                try:
                    imported_objects = download_and_import_model(model_url, file_format)

                    # Tag top-level imported objects with the job handle so
                    # list_recent_3d_imports can find them. Only tag roots —
                    # children inherit identity from parents and tagging every
                    # mesh would noise up the enumeration.
                    if job_handle and imported_objects:
                        from datetime import datetime, timezone
                        imported_at = datetime.now(timezone.utc).isoformat()
                        imported_set = set(imported_objects)
                        for obj in imported_objects:
                            parent = obj.parent
                            if parent is None or parent not in imported_set:
                                obj["mixar_job_handle"] = job_handle
                                obj["mixar_imported_at_iso"] = imported_at

                    complete_progress('image_to_3d')
                    scene.mixie_image_to_3d_is_generating = False

                    # Trigger UI redraw
                    for window in bpy.context.window_manager.windows:
                        for area in window.screen.areas:
                            if area.type in ("VIEW_3D", "MIXIE"):
                                area.tag_redraw()

                    logger.debug("[Agent Image to 3D] Successfully imported %s object(s)", len(imported_objects))

                except Exception as e:
                    reset_progress('image_to_3d')
                    scene.mixie_image_to_3d_is_generating = False
                    logger.error("[Agent Image to 3D] Failed to import model: %s", e)

            except Exception as e:
                logger.error("[Agent Image to 3D] %s", e, exc_info=True)
                reset_progress('image_to_3d')
                scene.mixie_image_to_3d_is_generating = False

        def on_error(error):
            """Handle generation error."""
            # Skip if this callback belongs to a superseded generation
            if my_generation_id != _current_agent_generation_id:
                logger.info(
                    "[Agent Image to 3D] Ignoring stale error (id=%d, current=%d)",
                    my_generation_id, _current_agent_generation_id,
                )
                return

            error_str = str(error) if error else "Unknown error"
            reset_progress('image_to_3d')
            scene.mixie_image_to_3d_is_generating = False
            logger.error("[Agent Image to 3D] %s", error_str)

        def on_complete(async_response):
            """Handle completion."""
            # Skip if this callback belongs to a superseded generation
            if my_generation_id != _current_agent_generation_id:
                return

            if scene.mixie_image_to_3d_is_generating:
                error = getattr(async_response, "error", None)
                response = getattr(async_response, "response", None)

                if error:
                    reset_progress('image_to_3d')
                    scene.mixie_image_to_3d_is_generating = False
                elif response and not response.success:
                    error_msg = getattr(response, "error", None)
                    if not error_msg and response.data:
                        error_msg = response.data.get("message", "Unknown error")
                    reset_progress('image_to_3d')
                    scene.mixie_image_to_3d_is_generating = False
                else:
                    scene.mixie_image_to_3d_is_generating = False

                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type in ("VIEW_3D", "MIXIE"):
                            area.tag_redraw()

        # Start async generation
        try:
            service.generate_async(
                image=image_bytes,
                model_name=model,
                prompt=prompt,
                parameters=parameters,
                on_success=on_success,
                on_error=on_error,
                on_complete=on_complete,
            )
        except Exception as e:
            scene.mixie_image_to_3d_is_generating = False
            reset_progress('image_to_3d')
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"3D model generation started with {model}...")
        return {"FINISHED"}


classes = (MIXIE_OT_agent_image_to_3d,)
