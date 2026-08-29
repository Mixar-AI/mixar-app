# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Retopology enqueue helpers — payload construction + per-object fan-out.

Builds payloads and calls ``enqueue_generation(kind="glb")`` for each
selected mesh object.  The retopology ``on_imported`` hook handles
post-processed vs. unprocessed mesh detection and fallback cleanup.
"""

import base64 as _b64
import os

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue.constants import FEATURE_RETOPOLOGY
from mixar.modules.common.job_queue.core.enqueue import enqueue_generation
from ..constants import (
    MAX_FILE_SIZE_TOPOLOGY,
    MAX_FILE_SIZE_TRIPO_RETOPOLOGY,
    RETOPOLOGY_HUNYUAN_MODEL,
    RETOPOLOGY_HUNYUAN_SERVICE,
    RETOPOLOGY_TRIPO_MODEL,
    RETOPOLOGY_TRIPO_SERVICE,
)
from mixar.modules.common.job_queue.core.model_io import export_selected_mesh

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared param snapshot
# ---------------------------------------------------------------------------


def snapshot_shared_params(topo) -> dict:
    """Capture the Topology UI's shared params into a dict."""
    return {
        "model": topo.model,
        "polygon_type": topo.polygon_type,
        "face_level": topo.face_level,
        "post_process": topo.post_process,
        "tripo_face_limit": topo.tripo_face_limit,
        "tripo_quad": topo.tripo_quad,
        "tripo_bake": topo.tripo_bake,
    }


# ---------------------------------------------------------------------------
# on_imported hook
# ---------------------------------------------------------------------------


def _retopology_on_imported(job, object_names: str) -> None:
    """Post-import for retopology: detect post-processed mesh or fallback.

    Either branch also runs ``finalize_generated_material`` on the result so a
    BAKED retopology (Tripo ``bake=True``) gets its messy provider material /
    image names cleaned to the ``<mesh>_*`` convention and any packed
    metallicRoughness split into separate images. A no-op for geometry-only
    retopology that carries no textured material.
    """
    from mixar.modules.common.job_queue.core.model_io import (
        post_import_rename_and_setup,
    )
    from mixar.modules.moodboard.core.imported_pbr_layers import (
        convert_imported_material_to_paint_layers,
    )
    names = [n.strip() for n in object_names.split(",") if n.strip()]
    has_low_suffix = any("_low" in n for n in names)

    if has_low_suffix:
        logger.info("[Retopology] Post-processed mesh detected, skipping client-side cleanup")
        final = next(
            (n for n in names
             if (o := bpy.data.objects.get(n)) is not None and o.type == 'MESH'),
            None,
        )
    else:
        logger.warning("[Retopology] Unprocessed mesh detected, applying client-side fallback")
        target = _strip_high_suffix(job.label) + "_low"
        final = None
        try:
            final = post_import_rename_and_setup(object_names, target, smart_uv=True)
        except Exception as e:
            logger.warning("[Retopology] post_import_rename_and_setup failed: %s", e)

    if final:
        try:
            convert_imported_material_to_paint_layers(final)
        except Exception as e:
            logger.warning("[Retopology] material finalize failed: %s", e)


def _strip_high_suffix(name: str) -> str:
    """Drop a trailing ``_high`` (any case) and any file extension from a name."""
    base = os.path.splitext(name)[0] if "." in name else name
    for suffix in ("_high", "_High", "_HIGH"):
        if base.endswith(suffix):
            return base[:-len(suffix)]
    return base


def _make_tripo_on_imported(bake: bool):
    """Build the Tripo retopology ``on_imported`` hook.

    Tripo's decimated GLB is already a finished low-poly (no GPU post-process),
    so we only rename to the ``*_low`` convention. We Smart-UV unwrap **only**
    when ``bake`` is False — when baking, Tripo bakes textures onto the existing
    UVs, so re-unwrapping would discard them.
    """

    def _on_imported(job, object_names: str) -> None:
        from mixar.modules.common.job_queue.core.model_io import (
            post_import_rename_and_setup,
        )
        from mixar.modules.moodboard.core.imported_pbr_layers import (
            convert_imported_material_to_paint_layers,
        )
        target = _strip_high_suffix(job.label) + "_low"
        final = None
        try:
            final = post_import_rename_and_setup(
                object_names, target, smart_uv=not bake)
        except Exception as e:
            logger.warning("[Retopology/Tripo] post_import_rename_and_setup failed: %s", e)

        # Baked Tripo output carries a textured material — rebuild it as a paint
        # fill layer (maps into channel slots). No-op when bake=False (no textures).
        if final:
            try:
                convert_imported_material_to_paint_layers(final)
            except Exception as e:
                logger.warning("[Retopology/Tripo] material finalize failed: %s", e)

    return _on_imported


# ---------------------------------------------------------------------------
# Single-object export
# ---------------------------------------------------------------------------


def _export_single_object(context, obj) -> tuple:
    """Export ``obj`` alone as GLB. Returns ``(bytes, filename)``.

    Snapshots the current selection, isolates ``obj``, exports, then
    restores the original selection / active object.
    """
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
        obj.select_set(True)
        view_layer.objects.active = obj
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


# ---------------------------------------------------------------------------
# Fan-out enqueue
# ---------------------------------------------------------------------------


def enqueue_retopology_jobs(
    *,
    context,
    objects: list,
    shared: dict,
    operator=None,
) -> list:
    """Fan out a list of selected mesh objects into per-object queue jobs.

    Each object is exported individually as GLB. Files exceeding the
    backend size limit are skipped with a warning.
    """
    enqueued: list = []
    is_tripo = shared.get("model", "hunyuan") == "tripo"
    max_size = (
        MAX_FILE_SIZE_TRIPO_RETOPOLOGY if is_tripo else MAX_FILE_SIZE_TOPOLOGY
    )

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

        if len(file_bytes) > max_size:
            size_mb = len(file_bytes) / (1024 * 1024)
            msg = (
                f"Skipping '{obj.name}': exported file is {size_mb:.1f}MB "
                f"(max {max_size // (1024 * 1024)}MB)"
            )
            logger.warning(msg)
            if operator is not None:
                operator.report({'WARNING'}, msg)
            continue

        if is_tripo:
            job = _enqueue_tripo(obj, shared, file_bytes, filename)
        else:
            job = _enqueue_hunyuan(obj, shared, file_bytes, filename)
        if job is not None:
            enqueued.append(job)

    return enqueued


def _enqueue_hunyuan(obj, shared, file_bytes, filename):
    """Enqueue a Hunyuan retopology job (backend service ``retopology``).

    Sends catalog-schema params (polygon_type / face_level / post_process)
    as ``payload["params"]`` — the backend HunyuanAdapter owns the Tencent
    SDK mapping. The legacy props path and the catalog-driven tab funnel
    through here so both produce the same wire shape.
    """
    from mixar.modules.common.generation_params import assemble_payload

    model = shared.get("model_slug") or RETOPOLOGY_HUNYUAN_MODEL
    params = {
        "polygon_type": shared.get("polygon_type"),
        "face_level": shared.get("face_level"),
        "post_process": shared.get("post_process", True),
    }
    payload = assemble_payload(
        RETOPOLOGY_HUNYUAN_SERVICE,
        params,
        {
            "input_name": obj.name,
            "file_bytes_b64": _b64.b64encode(file_bytes).decode(),
            "file_filename": filename,
        },
        model,
    )

    return enqueue_generation(
        kind="glb",
        feature_key=FEATURE_RETOPOLOGY,
        job_type=RETOPOLOGY_HUNYUAN_SERVICE,
        model=model,
        payload=payload,
        label=obj.name,
        fail_message="Retopology failed",
        on_imported=_retopology_on_imported,
        scene_flag="mixie_retopology_is_generating",
        batch_popup_title="Retopology batch complete",
    )


def _enqueue_tripo(obj, shared, file_bytes, filename):
    """Enqueue a Tripo retopology job.

    Submits to the service the catalog linked the Tripo model under —
    the merged ``retopology`` service on current catalogs (via
    ``shared["service_key"]``), or the legacy ``retopology_tripo``
    service pre-merge and for the old props path. Sends catalog-schema
    params (quad / face_limit / bake) as ``payload["params"]`` — the
    backend TripoAdapter owns the decimate body and face-limit clamping.
    Shares the same client queue (``FEATURE_RETOPOLOGY``) as Hunyuan.
    """
    from mixar.modules.common.generation_params import assemble_payload

    service = shared.get("service_key") or RETOPOLOGY_TRIPO_SERVICE
    model = shared.get("model_slug") or RETOPOLOGY_TRIPO_MODEL
    bake = bool(shared.get("tripo_bake", True))
    params = {
        "quad": bool(shared.get("tripo_quad", False)),
        "face_limit": shared.get("tripo_face_limit", 10000),
        "bake": bake,
    }
    payload = assemble_payload(
        service,
        params,
        {
            "input_name": obj.name,
            "file_bytes_b64": _b64.b64encode(file_bytes).decode(),
            "file_filename": filename,
        },
        model,
    )

    return enqueue_generation(
        kind="glb",
        feature_key=FEATURE_RETOPOLOGY,
        job_type=service,
        model=model,
        payload=payload,
        label=obj.name,
        fail_message="Retopology failed",
        on_imported=_make_tripo_on_imported(bake),
        scene_flag="mixie_retopology_is_generating",
        batch_popup_title="Retopology batch complete",
    )
