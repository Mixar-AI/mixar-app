# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene Gen Experimental labels queue: concrete Job + enqueue helper.

Submits a scene reconstruction job with ``generate_mesh=False`` so the
backend runs the full SAM3D pipeline but skips 3D mesh generation.
Once Phase 2 completes, the extracted object *labels* (and spatial
metadata) are stored in the Scene Gen Exp tab for the user to select
which objects to generate images for.
"""

import base64 as _b64
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.analytics.draft_events import note_generation_submitted
from mixar.modules.common.api.services.job_queue_service import (
    get_job_queue_service,
)
from mixar.modules.common.job_queue import Job, JobState, get_queue
from mixar.modules.common.job_queue.core.job import FAILED_BACKEND_STATUSES
from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN_EXP_LABELS
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue

logger = get_logger(__name__)

_SERVICE_KEY = "scene_reconstruction"

TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "expired"}
POLL_INTERVAL_PHASE1 = 2.0
POLL_INTERVAL_PHASE2 = 1.0


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class SceneGenExpLabelsJob(Job):
    """Concrete Job for label extraction via scene reconstruction."""

    # Submission payload
    image_bytes_b64: str = ""
    min_mask_pixels: int = 2000

    # Callbacks (set at enqueue, not serialized)
    _on_labels_ready: Optional[Callable] = field(default=None, repr=False)
    _on_error_callback: Optional[Callable] = field(default=None, repr=False)
    # Optional raw-objects hook: receives the Phase-2 objects array (label +
    # 3D box fields) regardless of whether the (disabled) tab is present. Used by
    # the World Labs scene-build flow to capture boxes into its own store.
    _on_objects: Optional[Callable] = field(default=None, repr=False)

    # Internal state
    _current_poll_interval: float = POLL_INTERVAL_PHASE1

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        service = get_job_queue_service()
        payload = {
            "image_bytes_b64": self.image_bytes_b64,
            "generate_mesh": False,
            "min_mask_pixels": self.min_mask_pixels,
            "mesh_postprocess": False,
            "texture_baking": False,
            "vertex_color": False,
        }
        service.enqueue(
            job_type=_SERVICE_KEY,
            model="sam3d",
            payload=payload,
            idempotency_key=self.submit_idempotency_key,
            on_success=on_success,
            on_error=on_error,
        )

    def poll(self, on_success, on_error) -> None:
        service = get_job_queue_service()
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
        # Release large payload memory
        self.image_bytes_b64 = ""

    def parse_poll_response(self, response):
        data = getattr(response, "data", None) or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        if not isinstance(inner, dict):
            return ("WAIT", [])

        gq_status = inner.get("status", "")
        result = inner.get("result") or {}

        if gq_status in FAILED_BACKEND_STATUSES:
            self.error = inner.get("error", "Label extraction failed")
            self.user_message = inner.get("user_message", "") or "Label extraction failed"
            return ("FAIL", [])
        if gq_status == "PENDING":
            self.backend_status = gq_status
            return ("WAIT", [])

        scene_data = result if isinstance(result, dict) else {}
        if gq_status == "DONE" and not scene_data.get("status"):
            scene_data["status"] = "completed"

        phase = scene_data.get("phase")
        if phase:
            return self._handle_phase2(scene_data)
        return self._handle_phase1(scene_data, gq_status)

    def handle_result(self, result_files, on_done, on_error):
        """Labels already stored during polling. Signal done."""
        if self._on_labels_ready:
            try:
                self._on_labels_ready()
            except Exception as e:
                logger.error("[SceneGenExp] labels_ready callback error: %s", e)
        on_done("Labels extracted")
        return True

    def get_poll_interval(self):
        return self._current_poll_interval

    # ------------------------------------------------------------------ #
    # Phase 1 — GPU server processing
    # ------------------------------------------------------------------ #

    def _handle_phase1(self, data: dict, gq_status: str):
        job_status = data.get("status", "")
        self.backend_status = gq_status or job_status

        stage_name = data.get("stage_name", "") or ""
        stage_detail = data.get("stage_detail", "") or ""
        detail_text = (
            stage_name
            + (" — " if stage_name and stage_detail else "")
            + stage_detail
        ) or "Processing..."
        _update_tab_status(stage_detail=detail_text)

        if job_status == "failed":
            self.error = data.get("error", "Job failed")
            self.user_message = data.get("user_message", "") or "Label extraction failed"
            _update_tab_status(error=self.error)
            return ("FAIL", [])
        if job_status in TERMINAL_JOB_STATUSES and job_status != "completed":
            self.error = f"Job ended: {job_status}"
            _update_tab_status(error=self.error)
            return ("FAIL", [])

        if gq_status in ("SUBMITTED", "POLLING"):
            return ("RUN", [])
        return ("WAIT", [])

    # ------------------------------------------------------------------ #
    # Phase 2 — object parsing (labels extraction)
    # ------------------------------------------------------------------ #

    def _handle_phase2(self, data: dict):
        phase = data.get("phase", "")
        job_status = data.get("status", "")
        total = data.get("total_objects", 0)
        completed = data.get("completed_objects", 0)
        objects = data.get("objects", [])
        error = data.get("error")

        self._current_poll_interval = POLL_INTERVAL_PHASE2

        if phase == "downloading_npz":
            _update_tab_status(stage_detail="Downloading scene data...")
        elif phase == "parsing":
            _update_tab_status(stage_detail="Parsing scene...")
        elif phase == "model_generation":
            _update_tab_status(
                stage_detail=f"Detecting objects ({completed}/{total})...",
            )
        elif phase == "completed":
            self._store_labels(objects)
            return ("DONE", [])
        elif phase == "failed":
            # Backend may have extracted labels even on failure — recover.
            if objects:
                logger.warning(
                    "[SceneGenExp] Phase failed (%s) but %d objects available, recovering",
                    error, len(objects),
                )
                self._store_labels(objects)
                return ("DONE", [])
            self.error = error or "Scene analysis failed"
            _update_tab_status(error=self.error)
            return ("FAIL", [])

        # Job-level terminal status
        if job_status in TERMINAL_JOB_STATUSES and phase not in ("completed", "failed"):
            if job_status == "failed":
                self.error = error or "Job failed"
                _update_tab_status(error=self.error)
                return ("FAIL", [])
            if objects:
                self._store_labels(objects)
                return ("DONE", [])
            self.error = "No objects detected"
            _update_tab_status(error=self.error)
            return ("FAIL", [])

        return ("RUN", [])

    def _store_labels(self, objects: list) -> None:
        """Extract labels + spatial metadata from Phase 2 objects array."""
        # Fire the raw-objects hook first (independent of the tab UI).
        if self._on_objects:
            try:
                self._on_objects(objects)
            except Exception as e:  # noqa: BLE001
                logger.error("[SceneGenExp] on_objects callback error: %s", e)
        tab = _get_tab()
        if tab is None:
            return
        tab.objects.clear()
        for obj in objects:
            label = str(obj.get("label", "")).strip()
            if not label:
                label = f"object_{obj.get('index', len(tab.objects))}"
            item = tab.objects.add()
            item.label = label
            item.chain_id = str(uuid.uuid4())

            center = obj.get("center")
            if center and len(center) >= 3:
                item.center = (float(center[0]), float(center[1]), float(center[2]))
            dims = obj.get("dimensions")
            if dims and len(dims) >= 3:
                item.dimensions = (float(dims[0]), float(dims[1]), float(dims[2]))
            rot = obj.get("rotation")
            if rot and len(rot) >= 4:
                item.rotation = (float(rot[0]), float(rot[1]), float(rot[2]), float(rot[3]))
            scale = obj.get("scale")
            if scale is not None:
                item.obj_scale = float(scale)

        tab.has_result = True
        logger.info(
            "[SceneGenExp] Extracted %d labels from scene reconstruction",
            len(tab.objects),
        )


# ---------------------------------------------------------------------------
# Tab UI helpers
# ---------------------------------------------------------------------------


def _get_tab():
    try:
        scene = bpy.context.scene
        if not scene or not hasattr(scene, "mixie_moodboard_sidebar"):
            return None
        sidebar = scene.mixie_moodboard_sidebar
        if not hasattr(sidebar, "tab_scene_gen_exp"):
            return None
        return sidebar.tab_scene_gen_exp
    except Exception:
        return None


def _update_tab_status(stage_detail: str = "", error: str = "") -> None:
    tab = _get_tab()
    if tab is None:
        return
    if stage_detail:
        tab.stage_detail = stage_detail
    if error:
        tab.error_text = error
        tab.stage_detail = ""


# ---------------------------------------------------------------------------
# Enqueue helper
# ---------------------------------------------------------------------------


def enqueue_scene_gen_exp_labels_job(
    *,
    image_bytes: bytes,
    min_mask_pixels: int = 2000,
    on_labels_ready: Optional[Callable] = None,
    on_error: Optional[Callable] = None,
    on_objects: Optional[Callable] = None,
) -> Optional[SceneGenExpLabelsJob]:
    """Build a ``SceneGenExpLabelsJob`` and submit it to the queue."""
    job = SceneGenExpLabelsJob(
        feature_key=FEATURE_SCENE_GEN_EXP_LABELS,
        label="Scene Gen Exp Labels",
        service=_SERVICE_KEY,
        image_bytes_b64=_b64.b64encode(image_bytes).decode(),
        min_mask_pixels=min_mask_pixels,
        _on_labels_ready=on_labels_ready,
        _on_error_callback=on_error,
        _on_objects=on_objects,
    )
    queue = _get_labels_queue()
    # Non-emitting marker only — the backend emits generation.submitted
    # at the job-queue submit endpoint (feeds draft-abandonment suppression).
    note_generation_submitted("scene_gen")
    if not queue.submit(job):
        logger.warning("[SceneGenExp] duplicate labels job rejected")
        return None
    return job


# ---------------------------------------------------------------------------
# Queue listener
# ---------------------------------------------------------------------------


_listener_attached = False


def _on_queue_changed(queue: FeatureQueue) -> None:
    """Sync scene gen exp processing flag to queue activity."""
    try:
        scene = bpy.context.scene
    except Exception:
        return
    if scene is None:
        return

    has_work = queue.has_active_work()
    was_processing = bool(getattr(scene, "mixie_scene_gen_exp_is_processing", False))

    if has_work and not was_processing:
        try:
            scene.mixie_scene_gen_exp_is_processing = True
        except (AttributeError, TypeError):
            pass
        return

    if not has_work and was_processing:
        try:
            scene.mixie_scene_gen_exp_is_processing = False
        except (AttributeError, TypeError):
            pass

        # Invoke error callbacks for failed jobs
        snapshot = queue.snapshot()
        for j in snapshot:
            if j.state == JobState.FAILED and hasattr(j, "_on_error_callback"):
                cb = j._on_error_callback
                if cb:
                    try:
                        cb(j.error or "Label extraction failed")
                    except Exception:
                        pass

    # Redraw all areas so tab UI updates
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


def _get_labels_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_SCENE_GEN_EXP_LABELS)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
