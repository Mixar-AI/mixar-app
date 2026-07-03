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
import os

from mixar.config.logging_config import get_logger

from ...core.lookdev360_utils import (
    save_material_checkpoint,
    ensure_uv_unwrap,
    export_objects_to_obj,
    get_selected_mesh_objects,
)
from ...core.lookdev360_paint_integration import check_or_create_mpaint_setup
from mixar.modules.common.utils.image_utils import compress_for_service

logger = get_logger(__name__)


def _get_lookdev360_props(scene):
    """Get lookdev360 tab properties from sidebar."""
    if hasattr(scene, 'mixie_moodboard_sidebar') and scene.mixie_moodboard_sidebar:
        sidebar = scene.mixie_moodboard_sidebar
        if hasattr(sidebar, 'tab_lookdev360'):
            return sidebar.tab_lookdev360
    return None


# Placeholder enum ids that are never real catalog model slugs.
_PLACEHOLDERS = ("LOADING", "ERROR", "NONE", "")


def _resolve_catalog_settings(props):
    """(model_slug, resolution) from the generation catalog, when loaded.

    The tab's model dropdown wins when it names a valid ``pbr_gen`` model;
    otherwise the catalog default. Resolution comes from the model's
    schema-driven param group. Returns ("", None) when the catalog isn't
    loaded so the caller falls back to the legacy hardcoded enum.
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_default_model_slug, get_model,
        )
        from mixar.modules.common.generation_params import collect_params

        slug = getattr(props, 'model', '') if props else ''
        if slug in _PLACEHOLDERS or get_model("pbr_gen", slug) is None:
            slug = get_default_model_slug("pbr_gen") or ""
        if not slug:
            return "", None
        params = collect_params("pbr_gen", slug)
        resolution = params.get("resolution")
        return slug, (int(resolution) if resolution is not None else None)
    except Exception:
        return "", None


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

    # Direct invocation properties (used by agent scripts).
    prompt: bpy.props.StringProperty(default="")
    reference_image_name: bpy.props.StringProperty(default="")

    def execute(self, context):
        from mixar.modules.common.utils.agent_feedback import set_agent_gen_reason

        scene = context.scene

        # Get lookdev360 tab properties from sidebar
        props = _get_lookdev360_props(scene)

        # Direct invocation: prompt property set explicitly
        if self.prompt and self.prompt.strip():
            prompt = self.prompt.strip()
            reference_image = None
            if self.reference_image_name:
                reference_image = bpy.data.images.get(self.reference_image_name)
        elif self.from_chat:
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
            set_agent_gen_reason(context, "No prompt provided for PBR/lookdev360")
            self.report({'WARNING'}, "Please enter a prompt (press Enter to confirm your text)")
            return {'CANCELLED'}

        # Get selected mesh objects
        mesh_objects = get_selected_mesh_objects()
        if not mesh_objects:
            set_agent_gen_reason(context, "No mesh selected — select the mesh object(s) to texture first")
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

        # Step 4b: Get model + resolution — schema-driven from the catalog
        # when loaded, legacy hardcoded enum otherwise.
        model_slug, resolution = _resolve_catalog_settings(props)
        if resolution is None and props:
            res_str = getattr(props, 'resolution', '1024')
            try:
                resolution = int(res_str)
            except (ValueError, TypeError):
                resolution = 1024

        # Store references for the job
        stored_objects = [obj.name for obj in mesh_objects]

        # Submit via FeatureQueue
        try:
            import base64 as _b64
            from mixar.modules.moodboard.core.lookdev360_queue import enqueue_lookdev360_job

            # Read OBJ file bytes for the payload
            with open(obj_path, "rb") as f:
                mesh_bytes = f.read()

            job = enqueue_lookdev360_job(
                prompt=prompt.strip(),
                mesh_bytes_b64=_b64.b64encode(mesh_bytes).decode(),
                mesh_filename="model.obj",
                model=model_slug or "hunyuan-pbr",
                resolution=resolution,
                style_image_bytes_b64=(
                    _b64.b64encode(style_image_bytes).decode() if style_image_bytes else None
                ),
                reference_image_bytes_b64=(
                    _b64.b64encode(reference_image_bytes).decode() if reference_image_bytes else None
                ),
                stored_objects=stored_objects,
                stored_obj_path=obj_path,
            )
            if not job:
                self.report({'WARNING'}, "A duplicate Lookdev360 generation is already queued")
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to start generation: {e}")
            try:
                os.unlink(obj_path)
            except OSError:
                pass
            return {'CANCELLED'}

        from mixar.modules.common.job_queue.constants import FEATURE_LOOKDEV360
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
        mark_enqueued(FEATURE_LOOKDEV360)
        self.report({'INFO'}, "Added to queue")
        return {'FINISHED'}


classes = (
    MIXIE_OT_lookdev360_generate,
)
