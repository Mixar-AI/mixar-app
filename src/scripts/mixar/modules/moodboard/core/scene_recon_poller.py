# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Reconstruction Poller Mixin

Polling methods for SceneReconManager: Phase 1 (GPU server) and Phase 2
(progressive object delivery) status handling.
"""

import threading
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger
from ...common.api.services.scene_recon_service import get_scene_recon_service
from ...common.api.response import APIResponse
from .scene_recon_constants import (
    TERMINAL_JOB_STATUSES,
    POLL_INTERVAL_PHASE2,
)

logger = get_logger(__name__)


class SceneReconPollerMixin:
    """Polling methods mixed into SceneReconManager.

    Accesses manager state via self (resolved at runtime by MRO).
    """

    def _poll_job(self) -> Optional[float]:
        """Poll job status. Returns interval to continue or None to stop."""
        if not self._polling or not self._job_id:
            return None

        job_id = self._job_id

        def fetch_status():
            try:
                service = get_scene_recon_service()
                response = service.get_job_status(job_id)

                def handle_status():
                    self._handle_status_response(response)
                    return None

                bpy.app.timers.register(handle_status, first_interval=0.0)

            except Exception as e:
                error_msg = str(e)
                is_not_found = "not found" in error_msg.lower() or "404" in error_msg

                def report_error():
                    if is_not_found:
                        self._consecutive_poll_failures += 1
                        # Tolerate up to 5 consecutive 404s (transient when
                        # load balancer routes to a worker without the job)
                        if self._consecutive_poll_failures >= 5:
                            logger.error(
                                "[SceneRecon] Job lost on server after %s retries",
                                self._consecutive_poll_failures,
                            )
                            self._set_error("Job not found — server may have restarted")
                        else:
                            logger.warning(
                                "[SceneRecon] Poll got 404, retrying (%s/5)...",
                                self._consecutive_poll_failures,
                            )
                    else:
                        logger.error("[SceneRecon] Poll failed: %s", error_msg)
                    return None

                bpy.app.timers.register(report_error, first_interval=0.0)

        thread = threading.Thread(target=fetch_status, daemon=True)
        thread.start()

        return self._current_poll_interval

    def _handle_status_response(self, response: APIResponse):
        """Handle status poll response on main thread."""
        if not response.success:
            logger.warning("[SceneRecon] Status check failed: %s", response.message)
            return

        # Successful poll — reset consecutive failure counter
        self._consecutive_poll_failures = 0

        data = response.data or {}
        inner_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}

        # Detect Phase 2 by the presence of "phase" key
        phase = inner_data.get("phase") or data.get("phase")

        if phase:
            self._handle_phase2_status(inner_data if phase == inner_data.get("phase") else data)
        else:
            self._handle_phase1_status(data, inner_data)

    def _handle_phase1_status(self, data: dict, inner_data: dict):
        """Handle Phase 1 status (GPU server stages)."""
        job_status = inner_data.get("status") or data.get("status", "")
        stage_name = inner_data.get("stage_name") or data.get("stage_name", "")
        stage_detail = inner_data.get("stage_detail") or data.get("stage_detail", "")
        elapsed = inner_data.get("elapsed_seconds") or data.get("elapsed_seconds", 0.0)
        error = inner_data.get("error") or data.get("error")

        # Update UI
        status_text = job_status.replace("_", " ").title()
        self._phase = "scene_reconstruction"
        self._update_tab_status(stage_name, stage_detail, status_text, elapsed)

        if job_status == "failed":
            self._polling = False
            error_msg = error or "Job failed"
            logger.error("[SceneRecon] Job failed: %s", error_msg)
            self._set_error(error_msg)
        elif job_status in TERMINAL_JOB_STATUSES and job_status != "completed":
            self._polling = False
            self._set_error(f"Job ended: {job_status}")
        # Note: "completed" from Phase 1 will auto-trigger Phase 2 on backend,
        # so the next poll will return Phase 2 data with "phase" key.

    def _handle_phase2_status(self, data: dict):
        """Handle Phase 2 status (3D model generation)."""
        import time
        phase = data.get("phase", "")
        job_status = data.get("status", "")
        total = data.get("total_objects", 0)
        completed = data.get("completed_objects", 0)
        elapsed = data.get("elapsed_seconds", 0.0)
        objects = data.get("objects", [])
        error = data.get("error")

        # Record phase transitions
        if phase and "phase2_start" not in self._timings:
            self._timings["phase2_start"] = time.monotonic()
        self._phase = phase
        self._total_objects = total
        self._completed_objects = completed

        # Switch to fast polling during progressive delivery
        self._current_poll_interval = POLL_INTERVAL_PHASE2

        # Update Phase 2 UI properties
        self._update_tab_phase2(phase, total, completed, elapsed)

        # Update status display based on phase
        if phase == "downloading_npz":
            self._update_tab_status(
                "Downloading Scene Data", "Preparing for 3D generation...",
                "Running", elapsed,
            )
        elif phase == "parsing":
            self._update_tab_status(
                "Parsing Scene", "Extracting objects...",
                "Running", elapsed,
            )
        elif phase == "model_generation":
            self._update_tab_status(
                f"Generating 3D Models ({completed}/{total})", "",
                "Running", elapsed,
            )
        elif phase == "completed":
            self._update_tab_status(
                f"Scene Complete ({total} objects)", "",
                "Completed", elapsed,
            )
        elif phase == "failed":
            self._update_tab_status(
                "Generation Failed", error or "",
                "Failed", elapsed,
            )

        # Scan for newly completed objects to download
        for obj in objects:
            obj_status = obj.get("status", "")
            obj_index = obj.get("index")
            model_url = obj.get("model_url")

            if obj_status != "completed" or not model_url:
                continue
            if obj_index is None:
                continue
            if obj_index in self._downloaded_objects:
                continue
            if obj_index in self._pending_objects:
                continue

            # Queue for download
            self._pending_objects[obj_index] = obj
            logger.debug(
                "[SceneRecon] Queued object %s ('%s') for download",
                obj_index, obj.get('label', ''),
            )

        # Try to start downloads (up to concurrency limit)
        self._try_download_next()

        # Handle terminal status
        if job_status in TERMINAL_JOB_STATUSES:
            self._polling = False
            self._polling_stopped = True
            self._timings["phase2_end"] = time.monotonic()
            logger.debug("[SceneRecon] Phase 2 reached terminal status: %s", job_status)

            # When no objects were downloaded (e.g. generate_mesh=false),
            # emit bbox placeholders from the spatial metadata instead of erroring.
            no_downloads = (
                not self._downloaded_objects
                and not self._pending_objects
                and self._active_downloads == 0
            )
            if no_downloads and self._on_bbox_ready and objects:
                bbox_count = 0
                for obj in objects:
                    obj_center = obj.get("center")
                    obj_dims = obj.get("dimensions")
                    if obj_center and obj_dims:
                        obj_index = obj.get("index", bbox_count)
                        obj_label = obj.get("label", f"object_{obj_index}")
                        obj_rotation = obj.get("rotation", [1.0, 0.0, 0.0, 0.0])
                        obj_scale = obj.get("scale", 1.0)
                        obj_bbox_matrix = obj.get("bbox_pose_matrix")
                        try:
                            self._on_bbox_ready(
                                obj_center, obj_dims, obj_rotation,
                                obj_scale, obj_index, obj_label,
                                obj_bbox_matrix,
                            )
                            bbox_count += 1
                        except Exception as e:
                            logger.error(
                                "[SceneRecon] bbox_ready callback failed for %s: %s",
                                obj_index, e,
                            )
                if bbox_count > 0:
                    self._timings["bbox_end"] = time.monotonic()
                    logger.debug("[SceneRecon] Created %s bbox placeholders", bbox_count)
                    if self._on_complete:
                        try:
                            self._on_complete(total, bbox_count, 0)
                        except Exception as e:
                            logger.error("[SceneRecon] Completion callback error: %s", e)
                    self._finish_job()
                    return

            if job_status == "failed" and no_downloads:
                error_msg = error or "All model generations failed"
                self._set_error(error_msg)
                return

        # Check if we can finish
        self._try_finish_job()
