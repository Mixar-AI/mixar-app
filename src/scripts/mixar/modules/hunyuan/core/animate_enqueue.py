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
  the catalog params (preset list, in-place). The result is a clip-only
  GLB whose actions ``animation_merge`` moves onto that same rig.
"""

import base64 as _b64

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue.constants import FEATURE_ANIMATE
from mixar.modules.common.job_queue.core.enqueue import enqueue_generation
from mixar.modules.common.i18n import n_, rpt_
from ..constants import (
    ANIMATE_IMPORT_OPTIONS,
    ANIMATE_PRESETS_PARAM,
    ANIMATE_RIG_JOB_PROP,
    ANIMATE_RIG_SERVICE,
    ANIMATE_RIG_SKELETON_PROP,
    ANIMATE_RETARGET_SERVICE,
    MAX_FILE_SIZE_ANIMATE_RIG,
)
from .animate_presets import clip_name
from .animation_merge import merge_hook

logger = get_logger(__name__)

ANIMATE_SCENE_FLAG = "mixie_animate_is_generating"

# ---------------------------------------------------------------------------
# Import hooks
# ---------------------------------------------------------------------------


def show_armatures_in_front(object_names: str) -> None:
    """Draw every imported armature In Front of the mesh it deforms.

    The glTF importer only sets this alongside the bone-shape Icosphere,
    which ``ANIMATE_IMPORT_OPTIONS`` turns off.
    """
    import bpy

    for name in (n.strip() for n in object_names.split(",")):
        obj = bpy.data.objects.get(name) if name else None
        if obj is not None and obj.type == 'ARMATURE':
            obj.show_in_front = True


def stamp_rig_import(job, object_names: str) -> None:
    """Stamp every imported object with the rig job id and the rig's skeleton,
    and show the rig In Front.

    The rigged GLB imports as an armature with the skinned mesh parented
    under it; stamping ALL of them means the user can select any part of
    the import and the retarget still finds the link. The skeleton
    (``rig_skeleton`` beside ``result_files`` in the job result, kept on
    ``job.result_data``) is what the retarget presets are filtered by.
    Every Auto Rig entry point — the sidebar/agent ``enqueue_rig_jobs`` and
    the Moodboard Auto Rig card — lands through this one function.
    """
    import bpy

    names = [n.strip() for n in object_names.split(",") if n.strip()]
    skeleton = str((getattr(job, "result_data", None) or {}).get("rig_skeleton") or "")
    stamped = 0
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        try:
            obj[ANIMATE_RIG_JOB_PROP] = str(job.backend_job_id)
            if skeleton:
                obj[ANIMATE_RIG_SKELETON_PROP] = skeleton
            stamped += 1
        except Exception as e:
            logger.warning("[Animate] Could not stamp %s: %s", name, e)
    show_armatures_in_front(object_names)
    logger.info(
        "[Animate] Rig imported: stamped %d object(s) with job %s (%s)",
        stamped, job.backend_job_id, skeleton or "skeleton unknown",
    )


# ---------------------------------------------------------------------------
# Rig-link discovery (used by the Animate card and the agent operator)
# ---------------------------------------------------------------------------


def _find_rig_prop(obj, prop: str) -> str:
    """A rig stamp on ``obj``, its ancestors, or (for a mesh) its armature-
    modifier target. Empty string when the object isn't part of an Auto Rig
    import."""
    def stamp(target) -> str:
        getter = getattr(target, "get", None)  # ID properties; absent on a non-ID
        return str(getter(prop, "") or "") if getter else ""

    seen = set()
    current = obj
    while current is not None and getattr(current, "name", None) not in seen:
        seen.add(getattr(current, "name", None))
        value = stamp(current)
        if value:
            return value
        current = getattr(current, "parent", None)
    if obj is not None and getattr(obj, "type", None) == 'MESH':
        for mod in getattr(obj, "modifiers", None) or ():
            if mod.type == 'ARMATURE' and mod.object is not None:
                value = stamp(mod.object)
                if value:
                    return value
    return ""


def find_rig_job_id(obj) -> str:
    """OUR queue job id of the Auto Rig that produced ``obj`` ("" if none)."""
    return _find_rig_prop(obj, ANIMATE_RIG_JOB_PROP)


def find_rig_skeleton(obj) -> str:
    """The rig's skeleton ("biped", ...) when the rig job reported one."""
    return _find_rig_prop(obj, ANIMATE_RIG_SKELETON_PROP)


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
        logger.warning("Failed to export selected mesh(es): %s", e)
        if operator is not None:
            operator.report({'WARNING'}, rpt_(
                "Failed to export selected mesh(es): {error}").format(error=e))
        return []

    if len(file_bytes) > MAX_FILE_SIZE_ANIMATE_RIG:
        size_mb = len(file_bytes) / (1024 * 1024)
        max_mb = MAX_FILE_SIZE_ANIMATE_RIG // (1024 * 1024)
        msg = n_(
            "Skipping Auto Rig: combined export is {size_mb:.1f}MB "
            "(max {max_mb}MB)"
        )
        logger.warning(msg.format(size_mb=size_mb, max_mb=max_mb))
        if operator is not None:
            operator.report({'WARNING'}, rpt_(msg).format(size_mb=size_mb, max_mb=max_mb))
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
        fail_message=n_("Auto Rig failed"),
        on_imported=stamp_rig_import,
        import_options=ANIMATE_IMPORT_OPTIONS,
        scene_flag=ANIMATE_SCENE_FLAG,
    )
    return [job] if job is not None else []


def enqueue_retarget_job(
    *,
    rig_job_id: str,
    service_key: str,
    model: str,
    params: dict,
    label: str,
    rig_name: str = "",
    graph_node_id: str = "",
    on_merged=None,
):
    """Enqueue one retarget job for a rigged import (Animate card and agent).

    ``params`` are the catalog's (``animations`` preset list, in-place); the
    payload adds ``input_name`` and the rig job id. The result's clips are
    merged onto the rig stamped with that id (``rig_name`` is the fallback
    lookup); ``on_merged(job, character_names)`` runs after a successful
    merge, before the job records those names as its result.
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
    clips = ", ".join(clip_name(preset) for preset in params.get(ANIMATE_PRESETS_PARAM) or ())
    return enqueue_generation(
        kind="glb",
        feature_key=FEATURE_ANIMATE,
        job_type=service_key or ANIMATE_RETARGET_SERVICE,
        model=model,
        payload=payload,
        label=f"{label} ({clips})",
        display_label=label,
        graph_node_id=graph_node_id,
        fail_message=n_("Animate failed"),
        on_imported=merge_hook(str(rig_job_id), rig_name, on_merged),
        import_options=ANIMATE_IMPORT_OPTIONS,
        scene_flag=ANIMATE_SCENE_FLAG,
    )
