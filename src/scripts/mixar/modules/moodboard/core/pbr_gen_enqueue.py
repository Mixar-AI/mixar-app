# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PBR Generation enqueue helper — Tripo texture-model texturing.

Shared by BOTH entry points so export / guidance / payload / queue never
diverge (the auto-rig pattern):

* interactive ``mixie.pbr_gen_generate`` (reads the sidebar tab)
* agent ``mixie.agent_pbr_generate`` (explicit object_name + guidance)

One ``tripo_texture`` job is submitted per call. The selected mesh(es) are
exported as GLB (Tripo's ``input``), guidance is attached as Tripo's
mutually-exclusive ``texture_prompt`` (assembled server-side from the staged
payload — see ``TripoAdapter._build_texture_prompt``), and the returned
textured GLB imports as a new object through the standard AsyncGLBJob path.
"""

import base64 as _b64

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue.constants import FEATURE_PBR_GEN
from mixar.modules.common.job_queue.core.enqueue import enqueue_generation

logger = get_logger(__name__)

# Tripo caps input files at 150 MB.
MAX_PBR_MESH_FILE_SIZE = 150 * 1024 * 1024
PBR_GEN_SCENE_FLAG = "mixie_pbr_gen_is_generating"


def _export_objects_glb(context, objects):
    """Select exactly *objects*, export them as one GLB, restore selection.

    Mirrors ``retopology_enqueue._export_single_object`` but for an explicit
    object set, so the agent path can texture a named object that isn't the
    live viewport selection.
    """
    from mixar.modules.common.job_queue.core.model_io import export_selected_mesh

    view_layer = context.view_layer
    prev_selected = list(context.selected_objects)
    prev_active = view_layer.objects.active
    try:
        for o in list(view_layer.objects):
            if o.select_get():
                o.select_set(False)
        for o in objects:
            o.select_set(True)
        view_layer.objects.active = objects[0]
        return export_selected_mesh(context, "GLB")
    finally:
        for o in list(view_layer.objects):
            try:
                o.select_set(False)
            except (RuntimeError, ReferenceError):
                pass
        for o in prev_selected:
            try:
                o.select_set(True)
            except (RuntimeError, ReferenceError):
                pass
        try:
            view_layer.objects.active = prev_active
        except (ReferenceError, AttributeError):
            pass


def enqueue_pbr_texture_job(
    context, *, objects, service_key, model, prompt="",
    reference_image=None, style_only=False, view_images=None,
    params=None, label=None, operator=None,
):
    """Export *objects* as GLB, attach guidance, enqueue ONE tripo_texture job.

    Returns the ``Job`` or ``None`` on failure. On failure the reason is both
    reported through *operator* (interactive UX) AND written to
    ``window_manager['mixar_agent_gen_reason']`` (the agent's refusal channel).

    Guidance precedence mirrors the drawer: four positional *view_images*
    (front/left/back/right) → Tripo ``images``; else a single
    *reference_image* (→ ``style_image`` when *style_only* and a prompt is
    set, else a direct reference); else prompt-only text.
    """
    from mixar.modules.common.generation_params import assemble_payload
    from mixar.modules.common.utils.image_utils import compress_image_for_upload

    def _fail(msg):
        if operator is not None:
            operator.report({'ERROR'}, msg)
        else:
            logger.warning(msg)
        try:
            context.window_manager['mixar_agent_gen_reason'] = msg
        except Exception:
            pass
        return None

    meshes = [o for o in objects if getattr(o, "type", None) == 'MESH']
    if not meshes:
        return _fail("No mesh to texture")

    try:
        file_bytes, filename = _export_objects_glb(context, meshes)
    except Exception as e:
        return _fail(f"Failed to export mesh: {e}")
    if len(file_bytes) > MAX_PBR_MESH_FILE_SIZE:
        size_mb = len(file_bytes) / (1024 * 1024)
        return _fail(f"Exported mesh is {size_mb:.1f}MB (max 150MB)")

    payload = {
        "file_bytes_b64": _b64.b64encode(file_bytes).decode(),
        "file_filename": filename,
    }

    prompt = (prompt or "").strip()
    try:
        if view_images:
            if len(view_images) != 4 or not all(view_images):
                return _fail(
                    "Multiple Views needs all four images "
                    "(front, left, back, right)")
            payload["reference_images_b64"] = [
                _b64.b64encode(compress_image_for_upload(img)).decode()
                for img in view_images
            ]
        elif reference_image is not None:
            encoded = _b64.b64encode(
                compress_image_for_upload(reference_image)).decode()
            if style_only and prompt:
                payload["style_ref_image_bytes_b64"] = encoded
            else:
                payload["reference_image_bytes_b64"] = encoded
    except Exception as e:
        return _fail(f"Failed to process reference image: {e}")

    merged = dict(params or {})
    if prompt:
        merged["prompt"] = prompt
    payload = assemble_payload(service_key, merged, payload, model)

    label = label or meshes[0].name
    from mixar.modules.moodboard.core.generation_enqueue import (
        make_texture_reimport_on_imported,
    )
    try:
        job = enqueue_generation(
            kind="glb",
            feature_key=FEATURE_PBR_GEN,
            job_type=service_key,
            model=model,
            payload=payload,
            label=label,
            fail_message="PBR generation failed",
            on_imported=make_texture_reimport_on_imported(),
            scene_flag=PBR_GEN_SCENE_FLAG,
        )
    except Exception as e:
        return _fail(f"Failed to start generation: {e}")
    if job is None:
        return _fail(f"A duplicate PBR generation for '{label}' is already queued")
    return job
