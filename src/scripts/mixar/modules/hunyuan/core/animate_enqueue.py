# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Animate enqueue helpers — Tripo auto-rig and animation retarget.

Two job kinds behind the Animate moodboard tab:

* **Auto Rig** (``tripo_rig``): ALL selected meshes are exported together
  into ONE GLB and submitted as a SINGLE job, so a segmented character
  (a mesh split into parts) is rigged as one skeleton instead of one
  independent rig per part — and Tripo runs a single rig-check over the
  whole body plan rather than misreading each isolated part. The import
  hook stamps every imported object with :data:`ANIMATE_RIG_JOB_PROP` —
  OUR queue job id — which is the retarget input; the backend resolves it
  to Tripo's task id with an ownership check, so vendor task ids never
  reach the client.

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


def _export_objects_together(context, objects: list) -> tuple:
    """Export EVERY mesh in ``objects`` into ONE GLB. Returns ``(bytes,
    filename)``.

    Snapshots the current selection, isolates the target meshes, exports them
    as a single GLB (so a segmented character rigs as one model), then restores
    the original selection / active object.
    """
    from mixar.modules.common.job_queue.core.model_io import export_selected_mesh

    view_layer = context.view_layer
    prev_selected = list(context.selected_objects)
    prev_active = view_layer.objects.active

    def _deselect_all():
        for o in list(view_layer.objects):
            try:
                if o.select_get():
                    o.select_set(False)
            except (RuntimeError, ReferenceError):
                pass

    try:
        _deselect_all()
        active = None
        for o in objects:
            try:
                o.select_set(True)
                active = o
            except (RuntimeError, ReferenceError):
                pass
        if active is not None:
            view_layer.objects.active = active
        return export_selected_mesh(context, "GLB")
    finally:
        _deselect_all()
        for o in prev_selected:
            try:
                o.select_set(True)
            except (RuntimeError, ReferenceError):
                pass
        try:
            view_layer.objects.active = prev_active
        except (ReferenceError, AttributeError):
            pass


def _rig_label(context, meshes: list) -> str:
    """Queue label for the combined rig job: the active mesh's name (or the
    first selected), suffixed with the extra part count when several meshes
    are combined into one rig. A single mesh keeps its bare name so the agent
    operator's duplicate-label check still matches."""
    view_layer = getattr(context, "view_layer", None)
    active_obj = getattr(getattr(view_layer, "objects", None), "active", None)
    mesh_names = [m.name for m in meshes]
    active_name = getattr(active_obj, "name", None)
    if active_name in mesh_names:
        base = active_name
    elif mesh_names:
        base = mesh_names[0]
    else:
        base = "Auto Rig"
    if len(meshes) > 1:
        return f"{base} +{len(meshes) - 1}"
    return base


def enqueue_rig_jobs(
    *,
    context,
    objects: list,
    service_key: str,
    model: str,
    params: dict,
    operator=None,
) -> list:
    """Export ALL selected meshes into ONE GLB and submit a SINGLE Auto Rig
    job, so a segmented character (mesh split into parts) rigs as one skeleton
    rather than one independent rig per part.

    Returns a one-element list with the enqueued job (empty on failure), so
    callers can keep testing the result truthily.
    """
    from mixar.modules.common.generation_params import assemble_payload

    meshes = [o for o in objects if getattr(o, "type", None) == 'MESH']
    if not meshes:
        return []

    try:
        file_bytes, filename = _export_objects_together(context, meshes)
    except Exception as e:
        msg = f"Failed to export selected mesh(es): {e}"
        logger.warning(msg)
        if operator is not None:
            operator.report({'WARNING'}, msg)
        return []

    if len(file_bytes) > MAX_FILE_SIZE_ANIMATE_RIG:
        size_mb = len(file_bytes) / (1024 * 1024)
        msg = (
            f"Skipping Auto Rig: combined export is {size_mb:.1f}MB "
            f"(max {MAX_FILE_SIZE_ANIMATE_RIG // (1024 * 1024)}MB)"
        )
        logger.warning(msg)
        if operator is not None:
            operator.report({'WARNING'}, msg)
        return []

    label = _rig_label(context, meshes)
    payload = assemble_payload(
        service_key,
        dict(params),
        {
            "input_name": label,
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
        label=label,
        fail_message="Auto Rig failed",
        on_imported=_rig_on_imported,
        import_options=_ANIMATE_IMPORT_OPTIONS,
        scene_flag=ANIMATE_SCENE_FLAG,
        batch_popup_title="Auto Rig complete",
    )
    return [job] if job is not None else []


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
