# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene Reconstruction job queue: concrete Job + enqueue helpers.

Hardest migration — async type with progressive multi-object GLB delivery.
Phase 1: GPU server scene reconstruction (SAM3D stages).
Phase 2: Backend generates 3D models per object, delivered progressively.

Download helpers are in ``scene_recon_download_helpers.py`` to stay under
the 500-line limit.
"""

import base64 as _b64
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.job_queue_service import (
    get_job_queue_service,
)
from mixar.modules.common.job_queue import Job, JobState, get_queue
from mixar.modules.common.job_queue.core.job import FAILED_BACKEND_STATUSES
from mixar.modules.common.job_queue.constants import FEATURE_SCENE_RECON
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue
from .scene_recon_constants import (
    POLL_INTERVAL_PHASE1,
    POLL_INTERVAL_PHASE2,
    TERMINAL_JOB_STATUSES,
    MAX_CONCURRENT_DOWNLOADS,
)

logger = get_logger(__name__)

_SERVICE_KEY = "scene_reconstruction"


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class SceneReconJob(Job):
    """Concrete Job for scene reconstruction (async, progressive delivery)."""

    # Submission payload
    image_bytes_b64: str = ""
    generate_mesh: bool = True
    min_mask_pixels: int = 6000
    mesh_postprocess: bool = True
    texture_baking: bool = False
    vertex_color: bool = True

    # Callback fields (set at enqueue, not serialized)
    _on_object_ready: Optional[Callable] = field(default=None, repr=False)
    _on_download_failed: Optional[Callable] = field(default=None, repr=False)
    _on_bbox_ready: Optional[Callable] = field(default=None, repr=False)
    _on_complete_callback: Optional[Callable] = field(default=None, repr=False)
    _on_error_callback: Optional[Callable] = field(default=None, repr=False)

    # Internal progressive state
    _phase: str = ""
    _total_objects: int = 0
    _completed_objects: int = 0
    _failed_objects: List[Tuple[int, str, str]] = field(default_factory=list, repr=False)
    _downloaded_set: Set[int] = field(default_factory=set, repr=False)
    _pending_objects: Dict[int, dict] = field(default_factory=dict, repr=False)
    _active_downloads: int = 0
    _next_import_id: int = 0
    _downloaded_glbs: Dict[int, Optional[Tuple]] = field(default_factory=dict, repr=False)
    _current_poll_interval: float = POLL_INTERVAL_PHASE1
    _polling_stopped: bool = False
    _phase2_started: bool = False
    _imported_names: List[str] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        service = get_job_queue_service()
        payload = {
            "image_bytes_b64": self.image_bytes_b64,
            "generate_mesh": self.generate_mesh,
            "min_mask_pixels": self.min_mask_pixels,
            "mesh_postprocess": self.mesh_postprocess,
            "texture_baking": self.texture_baking,
            "vertex_color": self.vertex_color,
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

        # Release large payload memory after successful submission
        self.image_bytes_b64 = ""

    def parse_poll_response(self, response):
        data = getattr(response, "data", None) or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        if not isinstance(inner, dict):
            return ("WAIT", [])

        # Unwrap job queue envelope
        gq_status = inner.get("status", "")
        result = inner.get("result") or {}

        # Map job queue statuses
        if gq_status in FAILED_BACKEND_STATUSES:
            self.error = inner.get("error", "Scene reconstruction failed")
            self.user_message = inner.get("user_message", "") or "Scene reconstruction failed"
            return ("FAIL", [])
        if gq_status == "PENDING":
            self.backend_status = gq_status
            return ("WAIT", [])

        # For DONE/SUBMITTED/POLLING, extract scene recon data from result
        scene_data = result if isinstance(result, dict) else {}
        if gq_status == "DONE":
            if not scene_data.get("status"):
                scene_data["status"] = "completed"

        # Detect Phase 2 by the presence of "phase" key
        phase = scene_data.get("phase")
        if phase:
            return self._handle_phase2(scene_data)
        else:
            return self._handle_phase1(scene_data, gq_status)

    def handle_result(self, result_files, on_done, on_error):
        """Imports already happened during polling. Just signal done."""
        total = self._total_objects
        failed_count = len(self._failed_objects)
        succeeded = total - failed_count

        if self._on_complete_callback:
            try:
                self._on_complete_callback(total, succeeded, failed_count)
            except Exception as e:
                logger.error("[SceneRecon] Completion callback error: %s", e)

        # If every object failed, treat the whole job as failed
        if succeeded == 0 and total > 0:
            on_error(f"All {total} objects failed to generate")
            return True

        if self._imported_names:
            on_done(", ".join(self._imported_names))
        else:
            on_done(f"{succeeded}/{total} objects")
        return True

    def get_poll_interval(self):
        return self._current_poll_interval

    # ------------------------------------------------------------------ #
    # Phase 1 — GPU server processing
    # ------------------------------------------------------------------ #

    def _handle_phase1(self, data: dict, gq_status: str):
        """Handle Phase 1 status (GPU server stages)."""
        job_status = data.get("status", "")
        self.backend_status = gq_status or job_status

        # Update tab UI
        stage_name = data.get("stage_name", "")
        stage_detail = data.get("stage_detail", "")
        _update_tab_status(stage_name, stage_detail)

        if job_status == "failed":
            self.error = data.get("error", "Job failed")
            self.user_message = data.get("user_message", "") or "Scene reconstruction failed"
            _update_tab_status(error=self.error)
            return ("FAIL", [])
        if job_status in TERMINAL_JOB_STATUSES and job_status != "completed":
            self.error = f"Job ended: {job_status}"
            self.user_message = data.get("user_message", "") or "Scene reconstruction failed"
            _update_tab_status(error=self.error)
            return ("FAIL", [])

        if gq_status in ("SUBMITTED", "POLLING"):
            return ("RUN", [])
        return ("WAIT", [])

    # ------------------------------------------------------------------ #
    # Phase 2 — progressive object delivery
    # ------------------------------------------------------------------ #

    def _handle_phase2(self, data: dict):
        """Handle Phase 2 status (progressive 3D model delivery)."""
        from .scene_recon_download_helpers import try_download_next, try_import_next

        phase = data.get("phase", "")
        job_status = data.get("status", "")
        total = data.get("total_objects", 0) or data.get("total", 0)
        completed = data.get("completed_objects", 0) or data.get("completed", 0)
        objects = data.get("objects", [])
        error = data.get("error")

        # Reset timeout on Phase 2 start (queue wait shouldn't eat into it)
        if not self._phase2_started:
            self._phase2_started = True
            self.poll_start_time = time.time()

        self._phase = phase
        self._total_objects = total
        self._completed_objects = completed
        self._current_poll_interval = POLL_INTERVAL_PHASE2

        # Update tab UI
        if phase == "model_generation":
            _update_tab_status(
                f"Generating 3D Models ({completed}/{total})", "",
            )
        elif phase == "completed":
            _update_tab_status(f"Scene Complete ({total} objects)", "")

        # Scan for newly completed objects to download
        for obj in objects:
            obj_status = obj.get("status", "")
            obj_index = obj.get("index")
            model_url = obj.get("model_url")

            if obj_status != "completed" or not model_url:
                continue
            if obj_index is None:
                continue
            if obj_index in self._downloaded_set:
                continue
            if obj_index in self._pending_objects:
                continue

            self._pending_objects[obj_index] = obj

        # Start downloads
        try_download_next(self)

        # Handle terminal status
        if job_status in TERMINAL_JOB_STATUSES:
            self._polling_stopped = True

            # Handle bbox-only flow (generate_mesh=false)
            no_downloads = (
                not self._downloaded_set
                and not self._pending_objects
                and self._active_downloads == 0
            )
            if no_downloads and self._on_bbox_ready and objects:
                self._emit_bbox_placeholders(objects)
                return ("DONE", [])

            if job_status == "failed" and no_downloads:
                self.error = error or "All model generations failed"
                self.user_message = data.get("user_message", "") or "Scene reconstruction failed"
                return ("FAIL", [])

        # Check if all done
        if self._polling_stopped and self._active_downloads == 0 \
                and not self._pending_objects and not self._downloaded_glbs:
            return ("DONE", [])

        return ("RUN", [])

    def _emit_bbox_placeholders(self, objects: list) -> None:
        """Emit bbox placeholders for generate_mesh=false flow."""
        bbox_count = 0
        for obj in objects:
            center = obj.get("center")
            dims = obj.get("dimensions")
            if center and dims:
                idx = obj.get("index", bbox_count)
                label = obj.get("label", f"object_{idx}")
                rotation = obj.get("rotation", [1.0, 0.0, 0.0, 0.0])
                scale = obj.get("scale", 1.0)
                bbox_matrix = obj.get("bbox_pose_matrix")
                try:
                    self._on_bbox_ready(
                        center, dims, rotation, scale, idx, label, bbox_matrix,
                    )
                    bbox_count += 1
                except Exception as e:
                    logger.error("[SceneRecon] bbox_ready failed for %s: %s", idx, e)


# ---------------------------------------------------------------------------
# Tab UI helpers
# ---------------------------------------------------------------------------


def _update_tab_status(
    stage_name: str = "", stage_detail: str = "", error: str = "",
) -> None:
    """Update tab UI properties with current status."""
    try:
        scene = bpy.context.scene
        if not scene or not hasattr(scene, "mixie_moodboard_sidebar"):
            return
        sidebar = scene.mixie_moodboard_sidebar
        if not hasattr(sidebar, "tab_scene_recon"):
            return
        tab = sidebar.tab_scene_recon
        tab.stage_name = stage_name
        tab.stage_detail = stage_detail
        tab.error_text = error
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Enqueue helpers
# ---------------------------------------------------------------------------


def enqueue_scene_recon_job(
    *,
    image_bytes: bytes,
    generate_mesh: bool = True,
    min_mask_pixels: int = 6000,
    mesh_postprocess: bool = True,
    texture_baking: bool = False,
    vertex_color: bool = True,
    on_object_ready: Optional[Callable] = None,
    on_download_failed: Optional[Callable] = None,
    on_bbox_ready: Optional[Callable] = None,
    on_complete: Optional[Callable] = None,
    on_error: Optional[Callable] = None,
) -> Optional[SceneReconJob]:
    """Build a ``SceneReconJob`` and submit it to the queue."""
    job = SceneReconJob(
        feature_key=FEATURE_SCENE_RECON,
        label="Scene Reconstruction",
        service=_SERVICE_KEY,
        image_bytes_b64=_b64.b64encode(image_bytes).decode(),
        generate_mesh=generate_mesh,
        min_mask_pixels=min_mask_pixels,
        mesh_postprocess=mesh_postprocess,
        texture_baking=texture_baking,
        vertex_color=vertex_color,
        _on_object_ready=on_object_ready,
        _on_download_failed=on_download_failed,
        _on_bbox_ready=on_bbox_ready,
        _on_complete_callback=on_complete,
        _on_error_callback=on_error,
    )
    queue = _get_scene_recon_queue()
    if not queue.submit(job):
        logger.warning("[SceneRecon] duplicate job rejected")
        return None
    return job


# ---------------------------------------------------------------------------
# Queue listener
# ---------------------------------------------------------------------------


_listener_attached = False


def _on_queue_changed(queue: FeatureQueue) -> None:
    """Sync scene recon progress to queue activity."""
    try:
        scene = bpy.context.scene
    except Exception:
        return
    if scene is None:
        return

    has_work = queue.has_active_work()
    was_generating = bool(getattr(scene, "mixie_scene_recon_is_generating", False))

    if has_work and not was_generating:
        try:
            scene.mixie_scene_recon_is_generating = True
        except (AttributeError, TypeError):
            pass
        return

    if not has_work and was_generating:
        try:
            scene.mixie_scene_recon_is_generating = False
        except (AttributeError, TypeError):
            pass

        # Invoke error callbacks for failed jobs so the user sees the popup
        snapshot = queue.snapshot()
        for j in snapshot:
            if j.state == JobState.FAILED and hasattr(j, '_on_error_callback'):
                cb = j._on_error_callback
                if cb:
                    try:
                        cb(j.error or "Scene reconstruction failed")
                    except Exception:
                        pass


def _get_scene_recon_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_SCENE_RECON)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
