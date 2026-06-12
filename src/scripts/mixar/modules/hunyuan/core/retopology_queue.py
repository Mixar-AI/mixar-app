# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Retopology generation queue: concrete Job + per-object enqueue helpers.

Mirrors ``moodboard/core/image_to_3d_queue.py`` but for the Hunyuan
Topology service. The mesh file is exported and snapshotted at enqueue
time so the queue is decoupled from the user's selection state.
"""

from dataclasses import dataclass
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.generation_queue_service import get_generation_queue_service
from mixar.modules.common.job_queue import Job, JobState, get_queue
from mixar.modules.common.job_queue.constants import FEATURE_RETOPOLOGY
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue
from mixar.modules.moodboard.core.generate_progress import (
    complete_progress, reset_progress, start_progress,
)

from ..constants import MAX_FILE_SIZE_TOPOLOGY
from .hunyuan_helpers import export_selected_mesh

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class RetopologyJob(Job):
    """Concrete Job for the Hunyuan 3D Topology retopology flow."""

    _processing_started: bool = False
    file_bytes: bytes = b""
    file_filename: str = "export.glb"
    polygon_type: Optional[str] = None
    face_level: Optional[str] = None
    post_process: bool = True

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        sdk_params = {}
        if self.polygon_type:
            sdk_params["PolygonType"] = self.polygon_type
        if self.face_level:
            sdk_params["FaceLevel"] = self.face_level

        payload = {
            "sdk_params": sdk_params,
            "input_name": self.label,
            "post_process": self.post_process,
            "file_bytes_b64": __import__("base64").b64encode(self.file_bytes).decode(),
            "file_filename": self.file_filename,
        }

        service.enqueue(
            job_type="retopology",
            model="hunyuan_topology",
            payload=payload,
            on_success=on_success,
            on_error=on_error,
        )

    def poll(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        service.get_job_status(
            self.backend_job_id,
            on_success=on_success,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:
        data = getattr(response, "data", None) or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        self.backend_job_id = inner.get("job_id", "") if isinstance(inner, dict) else ""
        if not self.backend_job_id:
            raise ValueError("Enqueue response missing job_id")

    def parse_poll_response(self, response):
        data = getattr(response, "data", None) or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        if not isinstance(inner, dict):
            return ("WAIT", [])
        status = inner.get("status", "") or ""
        self.backend_status = status
        self.queue_position = inner.get("queue_position") or 0
        if status == "PENDING":
            return ("WAIT", [])
        if status in ("SUBMITTED", "POLLING"):
            if not self._processing_started:
                self._processing_started = True
                self.poll_start_time = __import__("time").time()
            return ("RUN", [])
        if status == "DONE":
            result = inner.get("result") or {}
            result_files = result.get("result_files", []) if isinstance(result, dict) else []
            return ("DONE", result_files)
        if status == "FAILED":
            error = inner.get("error", "")
            if error:
                self.error = error
            return ("FAIL", [])
        return ("WAIT", [])

    def on_imported(self, object_names: str) -> None:
        """Handle imported retopo mesh.

        If the result came from the post-processing backend (GLB with
        baked textures), the mesh is already named, pivoted, scaled,
        UV-unwrapped and textured — just call super().

        If post-processing was skipped (backend down / not configured),
        fall back to the original client-side cleanup: rename, remove
        empties, apply transforms, fix pivot, Smart UV.
        """
        super().on_imported(object_names)

        # Detect if post-processing was applied: a processed mesh will
        # already be named ``{base}_low`` and have UV layers with baked
        # textures.  An unprocessed Hunyuan result won't have ``_low``
        # in any imported object name.
        names = [n.strip() for n in object_names.split(",") if n.strip()]
        has_low_suffix = any("_low" in n for n in names)

        if has_low_suffix:
            logger.info("[Retopology] Post-processed mesh detected, skipping client-side cleanup")
            return

        # Fallback: post-processing was not applied — do client-side cleanup
        logger.warning("[Retopology] Unprocessed mesh detected, applying client-side fallback")
        import os
        name = os.path.splitext(self.label)[0] if "." in self.label else self.label
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
# Enqueue helpers
# ---------------------------------------------------------------------------


def snapshot_shared_params(topo) -> dict:
    """Capture the Topology UI's shared params into a dict."""
    return {
        "polygon_type": topo.polygon_type,
        "face_level": topo.face_level,
        "post_process": topo.post_process,
    }


def _export_single_object(context, obj) -> tuple:
    """Export ``obj`` alone as OBJ. Returns ``(bytes, filename)``.

    Snapshots the current selection, isolates ``obj``, exports, then
    restores the original selection / active object. Uses
    ``select_set`` rather than the ``object.select_all`` operator so
    it works regardless of the current Blender mode.
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


def enqueue_retopology_jobs(
    *,
    context,
    objects: list,
    shared: dict,
    operator=None,
) -> list:
    """Fan out a list of selected mesh objects into per-object queue jobs.

    Each object is exported individually as OBJ. Files exceeding the
    backend size limit are skipped with a warning (per Q6: skip-and-warn
    so the user immediately knows which one was rejected).
    """
    queue = _get_retopology_queue()
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

        job = RetopologyJob(
            feature_key=FEATURE_RETOPOLOGY,
            label=obj.name,
            file_bytes=file_bytes,
            file_filename=filename,
            polygon_type=shared.get("polygon_type"),
            face_level=shared.get("face_level"),
            post_process=shared.get("post_process", True),
        )
        queue.submit(job)
        enqueued.append(job)

    return enqueued


# ---------------------------------------------------------------------------
# Queue listener: drives shared progress bar + is_generating scene flag
# ---------------------------------------------------------------------------


_listener_attached = False


def _on_queue_changed(queue: FeatureQueue) -> None:
    """Sync the moodboard ``retopology`` progress bar to queue activity.

    Also fires the one-shot batch completion popup at the active→idle
    transition.
    """
    try:
        scene = bpy.context.scene
    except Exception:
        return
    if scene is None:
        return

    has_work = queue.has_active_work()
    was_generating = bool(getattr(scene, "mixie_retopology_is_generating", False))

    if has_work and not was_generating:
        try:
            scene.mixie_retopology_is_generating = True
        except (AttributeError, TypeError):
            pass
        start_progress("retopology")
        return

    if not has_work and was_generating:
        try:
            scene.mixie_retopology_is_generating = False
        except (AttributeError, TypeError):
            pass

        snapshot = queue.snapshot()
        succeeded = sum(1 for j in snapshot if j.state == JobState.SUCCESS)
        failed = sum(1 for j in snapshot if j.state == JobState.FAILED)
        cancelled = sum(1 for j in snapshot if j.state == JobState.CANCELLED)

        if succeeded > 0:
            complete_progress("retopology")
        else:
            reset_progress("retopology")

        if (succeeded + failed + cancelled) > 0:
            _show_batch_summary_popup(succeeded, failed, cancelled)


def _show_batch_summary_popup(succeeded: int, failed: int, cancelled: int) -> None:
    """Schedule a one-shot popup summarising the just-completed batch."""

    def _draw(self_menu, context):
        layout = self_menu.layout
        layout.label(text=f"Succeeded: {succeeded}", icon='CHECKMARK')
        if failed:
            layout.label(text=f"Failed: {failed}", icon='ERROR')
        if cancelled:
            layout.label(text=f"Cancelled: {cancelled}", icon='CANCEL')

    def _popup():
        try:
            wm = bpy.context.window_manager
            wm.popup_menu(
                _draw,
                title="Retopology batch complete",
                icon='INFO',
            )
        except Exception as e:
            logger.debug("Batch summary popup failed: %s", e)
        return None  # one-shot

    try:
        bpy.app.timers.register(_popup, first_interval=0.0)
    except Exception as e:
        logger.debug("Could not schedule batch summary popup: %s", e)


def _get_retopology_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_RETOPOLOGY)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
