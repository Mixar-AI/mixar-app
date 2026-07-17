# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Animate enqueue helpers — Tripo auto-rig and animation retarget.

Two job kinds behind the Animate moodboard tab:

* **Auto Rig** (``tripo_rig``): each selected mesh is exported alone as
  GLB (Tripo's rig-check accepts GLB only) and submitted through the
  unified queue. The import hook stamps every imported object with
  :data:`ANIMATE_RIG_JOB_PROP` — OUR queue job id — which is the retarget
  input; the backend resolves it to Tripo's task id with an ownership
  check, so vendor task ids never reach the client.

* **Animate** (``tripo_retarget``): no file upload — the payload carries
  the ``rig_job_id`` read from a previously imported rigged object plus
  the catalog params (animation preset, in-place). The result GLB comes
  back with the animation baked in and imports as a new animated copy.
"""

import base64 as _b64

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue.constants import FEATURE_ANIMATE
from mixar.modules.common.job_queue.core.enqueue import enqueue_generation
from ..constants import (
    ANIMATE_RIG_JOB_PROP,
    ANIMATE_RIG_SERVICE,
    ANIMATE_RETARGET_SERVICE,
    MAX_FILE_SIZE_ANIMATE_RIG,
)
from .retopology_enqueue import _export_single_object

logger = get_logger(__name__)

ANIMATE_SCENE_FLAG = "mixie_animate_is_generating"

# glTF import options for Tripo rigged / animated results. Tripo rigs are
# not authored in Blender, so Blender's default "Guess Original Bind Pose"
# reconstructs a bind pose that doesn't match what the animation was baked
# against — the mesh imports fine at rest but limbs collapse/cluster once
# the animation plays. Turning it off uses the glTF's own node transforms
# as the bind pose (what the animation expects). bone_heuristic=BLENDER is
# the importer default; pinned so a future default change can't regress us.
_ANIMATE_IMPORT_OPTIONS = {
    "bone_heuristic": "BLENDER",
    "guess_original_bind_pose": False,
}


# ---------------------------------------------------------------------------
# Import hooks
# ---------------------------------------------------------------------------


def _rig_on_imported(job, object_names: str) -> None:
    """Stamp every imported object with the rig job id.

    The rigged GLB imports as an armature with the skinned mesh parented
    under it; stamping ALL of them means the user can select any part of
    the import and the retarget operator still finds the link.
    """
    import bpy

    names = [n.strip() for n in object_names.split(",") if n.strip()]
    stamped = 0
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        try:
            obj[ANIMATE_RIG_JOB_PROP] = str(job.backend_job_id)
            stamped += 1
        except Exception as e:
            logger.warning("[Animate] Could not stamp %s: %s", name, e)
    logger.info(
        "[Animate] Rig imported: stamped %d object(s) with job %s",
        stamped, job.backend_job_id,
    )


# ---------------------------------------------------------------------------
# Rig-link discovery (used by the operator and the drawer)
# ---------------------------------------------------------------------------


def find_rig_job_id(obj) -> str:
    """Return the rig job id linked to ``obj``, searching the object, its
    ancestors, and (for a mesh) its armature-modifier target. Empty string
    when the object isn't part of an Auto Rig import."""
    seen = set()
    current = obj
    while current is not None and current.name not in seen:
        seen.add(current.name)
        value = current.get(ANIMATE_RIG_JOB_PROP, "")
        if value:
            return str(value)
        current = current.parent
    if obj is not None and getattr(obj, "type", None) == 'MESH':
        for mod in getattr(obj, "modifiers", []):
            if mod.type == 'ARMATURE' and mod.object is not None:
                value = mod.object.get(ANIMATE_RIG_JOB_PROP, "")
                if value:
                    return str(value)
    return ""


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


def enqueue_rig_jobs(
    *,
    context,
    objects: list,
    service_key: str,
    model: str,
    params: dict,
    operator=None,
) -> list:
    """Fan out selected meshes into per-object Auto Rig jobs."""
    from mixar.modules.common.generation_params import assemble_payload

    enqueued: list = []
    for obj in objects:
        if obj.type != 'MESH':
            continue
        try:
            file_bytes, filename = _export_single_object(context, obj)
        except Exception as e:
            msg = f"Failed to export '{obj.name}': {e}"
            logger.warning(msg)
            if operator is not None:
                operator.report({'WARNING'}, msg)
            continue

        if len(file_bytes) > MAX_FILE_SIZE_ANIMATE_RIG:
            size_mb = len(file_bytes) / (1024 * 1024)
            msg = (
                f"Skipping '{obj.name}': exported file is {size_mb:.1f}MB "
                f"(max {MAX_FILE_SIZE_ANIMATE_RIG // (1024 * 1024)}MB)"
            )
            logger.warning(msg)
            if operator is not None:
                operator.report({'WARNING'}, msg)
            continue

        payload = assemble_payload(
            service_key,
            dict(params),
            {
                "input_name": obj.name,
                "file_bytes_b64": _b64.b64encode(file_bytes).decode(),
                "file_filename": filename,
            },
            model,
        )
        job = enqueue_generation(
            kind="glb",
            feature_key=FEATURE_ANIMATE,
            job_type=service_key or ANIMATE_RIG_SERVICE,
            model=model,
            payload=payload,
            label=obj.name,
            fail_message="Auto Rig failed",
            on_imported=_rig_on_imported,
            import_options=_ANIMATE_IMPORT_OPTIONS,
            scene_flag=ANIMATE_SCENE_FLAG,
            batch_popup_title="Auto Rig batch complete",
        )
        if job is not None:
            enqueued.append(job)
    return enqueued


def enqueue_retarget_job(
    *,
    rig_job_id: str,
    service_key: str,
    model: str,
    params: dict,
    label: str,
):
    """Enqueue one retarget job for a rigged import.

    The animated GLB imports as a NEW copy (armature + mesh + baked
    action) beside the rigged one, so re-animating with a different
    preset never destroys the previous result.
    """
    from mixar.modules.common.generation_params import assemble_payload

    payload = assemble_payload(
        service_key,
        dict(params),
        {
            "input_name": label,
            "rig_job_id": str(rig_job_id),
        },
        model,
    )
    animation = str(params.get("animation") or "animation")
    short = animation.rsplit(":", 1)[-1]
    return enqueue_generation(
        kind="glb",
        feature_key=FEATURE_ANIMATE,
        job_type=service_key or ANIMATE_RETARGET_SERVICE,
        model=model,
        payload=payload,
        label=f"{label} ({short})",
        fail_message="Animate failed",
        import_options=_ANIMATE_IMPORT_OPTIONS,
        scene_flag=ANIMATE_SCENE_FLAG,
        batch_popup_title="Animate complete",
    )
