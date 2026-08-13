# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Texture Gen Operators

Generate operators for the consolidated, catalog-driven Texture Gen tab
(non-PBR modes — the ``pbr_gen`` mode keeps the existing
``mixie.lookdev360_generate`` pipeline operator):

- ``mixie.texture_edit_generate`` — Hunyuan texture edit: exports the
  selected mesh as FBX and submits job_type "hunyuan_texture_edit" with
  a reference image XOR prompt, sharing the FEATURE_LOOKDEV360 queue.
- ``mixie.texture_gen_matgen`` — procedural material generation: submits
  the prompt through the existing paint-side MatGen queue (wire payload
  {"prompt", "pipeline"} unchanged); results are saved to the procedural
  material library by the MatGen job handler.
"""

import base64 as _b64

from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.moodboard.core.media_utils import is_still_item

logger = get_logger(__name__)

# Backend limit for texture-edit mesh uploads (validator: 100MB FBX).
_MAX_TEXTURE_EDIT_FILE_SIZE = 100 * 1024 * 1024


def _get_texture_gen_tab(context):
    """The Texture Gen tab property group (or None)."""
    sidebar = getattr(context.scene, 'mixie_moodboard_sidebar', None)
    return getattr(sidebar, 'tab_lookdev360', None) if sidebar else None


def _resolve_model(tab, service_key, fallback):
    """The tab's model slug when valid for *service_key*, else the
    catalog default, else *fallback*."""
    from mixar.modules.common.generation_params import resolve_model_slug
    return resolve_model_slug(
        service_key, getattr(tab, 'model', '') if tab else '', fallback)


def _get_reference_image(context, tab):
    """Reference image from the shared image-source UI (or None)."""
    if getattr(tab, 'use_selected_image', False):
        scene = context.scene
        if hasattr(scene, 'mixie_moodboard_images'):
            for item in scene.mixie_moodboard_images:
                if item.selected and is_still_item(item):
                    return item.image
        return None
    return getattr(tab, 'reference_image', None)


class MIXIE_OT_texture_edit_generate(Operator):
    """Edit the selected mesh's textures with Hunyuan Texture Edit"""

    bl_idname = "mixie.texture_edit_generate"
    bl_label = "Texture Edit"
    bl_description = (
        "Edit the selected mesh's textures using a reference image or prompt"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        from mixar.modules.common.generation_params import (
            assemble_payload, collect_params,
        )
        from mixar.modules.common.utils.image_utils import (
            compress_image_for_upload,
        )
        from mixar.modules.common.job_queue.core.model_io import (
            export_selected_mesh,
        )

        tab = _get_texture_gen_tab(context)
        if tab is None:
            self.report({"WARNING"}, "Texture Gen tab not available")
            return {"CANCELLED"}

        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if not meshes:
            self.report({"WARNING"}, "No mesh selected")
            return {"CANCELLED"}

        model = _resolve_model(
            tab, "hunyuan_texture_edit", "hunyuan_texture_edit")

        # Reference image XOR prompt (vendor contract).
        image = _get_reference_image(context, tab)
        prompt = (getattr(tab, 'prompt', '') or '').strip()
        if image is None and not prompt:
            self.report(
                {"WARNING"}, "Provide a reference image or a prompt")
            return {"CANCELLED"}

        # Export the selected mesh as FBX (texture edit requires .fbx).
        try:
            file_bytes, filename = export_selected_mesh(context, "FBX")
        except Exception as e:
            self.report({"ERROR"}, f"Failed to export mesh: {e}")
            return {"CANCELLED"}
        if len(file_bytes) > _MAX_TEXTURE_EDIT_FILE_SIZE:
            size_mb = len(file_bytes) / (1024 * 1024)
            self.report(
                {"ERROR"},
                f"Exported mesh is {size_mb:.1f}MB (max 100MB)",
            )
            return {"CANCELLED"}

        payload = {
            "file_bytes_b64": _b64.b64encode(file_bytes).decode(),
            "file_filename": filename,
        }
        if image is not None:
            try:
                image_bytes = compress_image_for_upload(image)
            except Exception as e:
                self.report({"ERROR"}, f"Failed to process image: {e}")
                return {"CANCELLED"}
            payload["reference_image_bytes_b64"] = (
                _b64.b64encode(image_bytes).decode()
            )

        params = {}
        try:
            params = collect_params("hunyuan_texture_edit", model)
        except Exception as e:
            logger.debug("collect_params failed for texture edit: %s", e)
        # Prompt and reference image are mutually exclusive on the wire —
        # the image wins when both are present.
        if prompt and image is None:
            params["prompt"] = prompt
        payload = assemble_payload(
            "hunyuan_texture_edit", params, payload, model)

        from mixar.modules.common.job_queue import enqueue_generation
        from mixar.modules.common.job_queue.constants import FEATURE_LOOKDEV360
        from mixar.modules.moodboard.core.generation_enqueue import (
            make_texture_reimport_on_imported,
        )

        try:
            job = enqueue_generation(
                kind="glb",
                feature_key=FEATURE_LOOKDEV360,
                job_type="hunyuan_texture_edit",
                model=model,
                payload=payload,
                label=meshes[0].name,
                fail_message="Texture edit failed",
                on_imported=make_texture_reimport_on_imported(),
                scene_flag="mixie_lookdev360_is_generating",
            )
            if not job:
                self.report(
                    {"WARNING"}, "A duplicate texture edit is already queued")
                return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
            mark_enqueued,
        )
        mark_enqueued(FEATURE_LOOKDEV360)
        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}


class MIXIE_OT_texture_gen_matgen(Operator):
    """Generate a procedural material from the prompt"""

    bl_idname = "mixie.texture_gen_matgen"
    bl_label = "Generate Material"
    bl_description = (
        "Generate a procedural material with AI "
        "(saved to the Procedural Material library)"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        tab = _get_texture_gen_tab(context)
        if tab is None:
            self.report({"WARNING"}, "Texture Gen tab not available")
            return {"CANCELLED"}

        prompt = (getattr(tab, 'prompt', '') or '').strip()
        if not prompt:
            self.report({"WARNING"}, "Please enter a material description")
            return {"CANCELLED"}

        # mat_gen catalog model slugs ("fast" / "detailed") map onto the
        # MatGen pipeline field — the wire payload stays {"prompt",
        # "pipeline"} exactly as the paint-side MatGen popup sends it.
        pipeline = _resolve_model(tab, "mat_gen", "fast")

        try:
            from mixar.modules.paint.procedural_materials.matgen_queue import (
                enqueue_matgen_job,
            )
            job = enqueue_matgen_job(prompt=prompt, pipeline=pipeline)
            if job is None:
                self.report(
                    {"WARNING"},
                    "A duplicate material generation is already queued",
                )
                return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}


classes = (
    MIXIE_OT_texture_edit_generate,
    MIXIE_OT_texture_gen_matgen,
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
