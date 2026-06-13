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

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue.constants import FEATURE_RETOPOLOGY
from mixar.modules.common.job_queue.core.enqueue import enqueue_generation
from ..constants import MAX_FILE_SIZE_TOPOLOGY
from .hunyuan_helpers import export_selected_mesh

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared param snapshot
# ---------------------------------------------------------------------------


def snapshot_shared_params(topo) -> dict:
    """Capture the Topology UI's shared params into a dict."""
    return {
        "polygon_type": topo.polygon_type,
        "face_level": topo.face_level,
        "post_process": topo.post_process,
    }


# ---------------------------------------------------------------------------
# on_imported hook
# ---------------------------------------------------------------------------


def _retopology_on_imported(job, object_names: str) -> None:
    """Post-import for retopology: detect post-processed mesh or fallback."""
    names = [n.strip() for n in object_names.split(",") if n.strip()]
    has_low_suffix = any("_low" in n for n in names)

    if has_low_suffix:
        logger.info("[Retopology] Post-processed mesh detected, skipping client-side cleanup")
        return

    logger.warning("[Retopology] Unprocessed mesh detected, applying client-side fallback")
    name = os.path.splitext(job.label)[0] if "." in job.label else job.label
    for suffix in ("_high", "_High", "_HIGH"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    target = name + "_low"
    try:
        from .hunyuan_helpers import post_import_rename_and_setup
        post_import_rename_and_setup(object_names, target, smart_uv=True)
    except Exception as e:
        logger.warning("[Retopology] post_import_rename_and_setup failed: %s", e)


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

        if len(file_bytes) > MAX_FILE_SIZE_TOPOLOGY:
            size_mb = len(file_bytes) / (1024 * 1024)
            msg = (
                f"Skipping '{obj.name}': exported file is {size_mb:.1f}MB "
                f"(max {MAX_FILE_SIZE_TOPOLOGY // (1024 * 1024)}MB)"
            )
            logger.warning(msg)
            if operator is not None:
                operator.report({'WARNING'}, msg)
            continue

        sdk_params = {}
        if shared.get("polygon_type"):
            sdk_params["PolygonType"] = shared["polygon_type"]
        if shared.get("face_level"):
            sdk_params["FaceLevel"] = shared["face_level"]

        payload = {
            "sdk_params": sdk_params,
            "input_name": obj.name,
            "post_process": shared.get("post_process", True),
            "file_bytes_b64": _b64.b64encode(file_bytes).decode(),
            "file_filename": filename,
        }

        job = enqueue_generation(
            kind="glb",
            feature_key=FEATURE_RETOPOLOGY,
            job_type="retopology",
            model="hunyuan_topology",
            payload=payload,
            label=obj.name,
            fail_message="Retopology failed",
            on_imported=_retopology_on_imported,
            scene_flag="mixie_retopology_is_generating",
            batch_popup_title="Retopology batch complete",
        )
        if job is not None:
            enqueued.append(job)

    return enqueued
