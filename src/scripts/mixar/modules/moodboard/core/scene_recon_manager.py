# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Reconstruction Manager for Moodboard

Phase 1: Submit image -> poll GPU server stages -> auto-transition to Phase 2
Phase 2: Backend generates 3D models per object -> progressive GLB delivery to Blender

Downloads up to MAX_CONCURRENT_DOWNLOADS GLBs in parallel, but imports in order.

Polling logic: scene_recon_poller.SceneReconPollerMixin
Download logic: scene_recon_downloader.SceneReconDownloaderMixin
Shared constants: scene_recon_constants
"""

import threading
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

import bpy

from mixar.config.logging_config import get_logger
from ...common.api.services.generation_queue_service import get_generation_queue_service
from ...common.api.response import APIResponse
from .scene_recon_constants import (
    POLL_INTERVAL_PHASE1,
    TERMINAL_JOB_STATUSES,
    MAX_CONCURRENT_DOWNLOADS,
)
from .scene_recon_poller import SceneReconPollerMixin
from .scene_recon_downloader import SceneReconDownloaderMixin

logger = get_logger(__name__)


class SceneReconManager(SceneReconPollerMixin, SceneReconDownloaderMixin):
    """
    Singleton manager for Scene Reconstruction jobs.

    Handles two-phase workflow:
    - Phase 1: GPU server scene reconstruction (SAM3D stages)
    - Phase 2: Backend-orchestrated 3D model generation (progressive per-object delivery)

    Downloads up to MAX_CONCURRENT_DOWNLOADS objects in parallel, but imports
    sequentially on the main thread (Z-offset calculation depends on order).
    """

    def __init__(self):
        self._job_id: Optional[str] = None
        self._polling: bool = False
        self._on_complete: Optional[Callable] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_object_ready: Optional[Callable] = None
        self._on_download_failed: Optional[Callable] = None
        self._on_bbox_ready: Optional[Callable] = None

        # Phase 2 tracking
        self._phase: str = ""
        self._downloaded_objects: Set[int] = set()
        self._pending_objects: Dict[int, dict] = {}
        self._total_objects: int = 0
        self._completed_objects: int = 0
        self._polling_stopped: bool = False

        # Parallel download state
        self._active_downloads: int = 0
        self._next_import_id: int = 0
        self._downloaded_glbs: Dict[int, Optional[Tuple]] = {}  # obj_id -> (glb_bytes, pose_data, label) or None

        # Failure tracking
        self._failed_objects: List[Tuple[int, str, str]] = []  # (index, label, error)

        # Consecutive poll failure counter (for transient 404s across workers)
        self._consecutive_poll_failures: int = 0

        # Adaptive polling interval
        self._current_poll_interval: float = POLL_INTERVAL_PHASE1

        # Timing instrumentation
        self._timings: Dict[str, float] = {}

    @property
    def is_generating(self) -> bool:
        """Check if a job is currently active."""
        return self._job_id is not None

    def submit_job(
        self,
        image_bytes: bytes,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_object_ready: Optional[Callable] = None,
        on_download_failed: Optional[Callable] = None,
        on_bbox_ready: Optional[Callable] = None,
        generate_mesh: bool = True,
        min_mask_pixels: int = 2000,
        mesh_postprocess: bool = True,
        texture_baking: bool = False,
        vertex_color: bool = True,
    ) -> bool:
        """
        Submit a scene reconstruction job.

        Args:
            image_bytes: PNG/JPG/WEBP image bytes
            on_complete: Callback(total, succeeded, failed_count) when all objects delivered
            on_error: Callback(error_message) on failure
            on_object_ready: Callback(glb_bytes, pose_data, object_id, label) per object
            on_download_failed: Callback(index, label, error) per failed download
            on_bbox_ready: Callback(center, dimensions, rotation, scale, object_id, label)
                           for bbox-only objects (no mesh)

        Returns:
            True if job was submitted, False if already generating
        """
        if self._job_id is not None:
            logger.warning("[SceneRecon] Already has an active job")
            return False

        self._on_complete = on_complete
        self._on_error = on_error
        self._on_object_ready = on_object_ready
        self._on_download_failed = on_download_failed
        self._on_bbox_ready = on_bbox_ready

        # Reset state
        self._phase = "scene_reconstruction"
        self._downloaded_objects = set()
        self._pending_objects = {}
        self._total_objects = 0
        self._completed_objects = 0
        self._polling_stopped = False
        self._active_downloads = 0
        self._next_import_id = 0
        self._downloaded_glbs = {}
        self._failed_objects = []
        self._consecutive_poll_failures = 0
        self._current_poll_interval = POLL_INTERVAL_PHASE1

        import base64 as _b64

        payload = {
            "image_bytes_b64": _b64.b64encode(image_bytes).decode(),
            "generate_mesh": generate_mesh,
            "min_mask_pixels": min_mask_pixels,
            "mesh_postprocess": mesh_postprocess,
            "texture_baking": texture_baking,
            "vertex_color": vertex_color,
        }

        def on_submit_success(response):
            self._handle_submit_response(response)

        def on_submit_error(error):
            error_msg = str(error)
            logger.error("[SceneRecon] Submit failed: %s", error_msg)
            self._set_error(error_msg)

        try:
            service = get_generation_queue_service()
            service.enqueue(
                job_type="scene_reconstruction",
                model="sam3d",
                payload=payload,
                on_success=on_submit_success,
                on_error=on_submit_error,
            )
        except Exception as e:
            self._set_error(str(e))
            return False

        # Set generating state
        self._set_generating(True)
        self._timings["submit_start"] = time.monotonic()
        logger.debug("[SceneRecon] Submitting job...")
        return True

    def _handle_submit_response(self, response: APIResponse):
        """Handle submit response on main thread."""
        if not response.success:
            error_msg = response.message or "Job submission failed"
            logger.error("[SceneRecon] Submit failed: %s", error_msg)
            self._set_error(error_msg)
            return

        data = response.data or {}
        inner_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        job_id = inner_data.get("job_id") or data.get("job_id")

        if not job_id:
            self._set_error("No job_id in response")
            return

        self._job_id = job_id
        self._timings["submit_end"] = time.monotonic()
        logger.debug("[SceneRecon] Job submitted")

        # Update UI status
        self._update_tab_status("Queued", "", "Waiting to start...")

        # Start polling
        self._start_polling()

    def _start_polling(self):
        """Start polling timer."""
        self._polling = True

        def poll_timer():
            return self._poll_job()

        bpy.app.timers.register(poll_timer, first_interval=self._current_poll_interval)

    def _try_finish_job(self):
        """Finish job only when polling stopped, no active downloads, and no buffered GLBs."""
        if not self._polling_stopped:
            return
        if self._active_downloads > 0:
            return
        if self._pending_objects:
            return
        if self._downloaded_glbs:
            return

        # All done
        total = self._total_objects
        failed_count = len(self._failed_objects)
        succeeded = total - failed_count
        logger.debug("[SceneRecon] All objects delivered, finishing job (%s/%s succeeded)", succeeded, total)

        if self._on_complete:
            try:
                self._on_complete(total, succeeded, failed_count)
            except Exception as e:
                logger.error("[SceneRecon] Completion callback error: %s", e)

        self._finish_job()

    def cancel_job(self) -> bool:
        """Cancel the active job."""
        if not self._job_id:
            return False

        job_id = self._job_id
        self._polling = False

        # Cancel on server
        def cancel_call():
            try:
                service = get_generation_queue_service()
                service.cancel_job(job_id)
                logger.debug("[SceneRecon] Cancelled job")
            except Exception as e:
                logger.error("[SceneRecon] Cancel failed: %s", e)

        thread = threading.Thread(target=cancel_call, daemon=True)
        thread.start()

        self._finish_job(success=False)
        return True

    @property
    def timings(self) -> Dict[str, float]:
        """Return a copy of the current timing data."""
        return dict(self._timings)

    def _print_timing_summary(self):
        """Print timing summary for each stage."""
        t = self._timings
        if not t:
            return

        def _dur(start_key: str, end_key: str) -> Optional[float]:
            s, e = t.get(start_key), t.get(end_key)
            return (e - s) if s is not None and e is not None else None

        logger.debug("[SceneRecon] ===== Timing Summary =====")
        parts = [
            ("Job Submission", _dur("submit_start", "submit_end")),
            ("Phase 1 (GPU Processing)", _dur("submit_end", "phase2_start")),
            ("Phase 2 (Model Generation)", _dur("phase2_start", "phase2_end")),
            ("Bbox Placeholder Creation", _dur("phase2_end", "bbox_end")),
        ]
        total_dur = _dur("submit_start", "bbox_end")

        for label, dur in parts:
            if dur is not None:
                logger.debug("[SceneRecon]   %s: %.2fs", label, dur)
            else:
                logger.debug("[SceneRecon]   %s: —", label)

        if total_dur is not None:
            logger.debug("[SceneRecon]   -- Total (recon): %.2fs", total_dur)
        logger.debug("[SceneRecon] ================================")

    def _finish_job(self, success: bool = True):
        """Clean up after job completion or cancellation.

        Args:
            success: True for normal completion (fast-fill progress to 100%),
                False for error paths (reset progress to zero).
        """
        self._print_timing_summary()
        self._job_id = None
        self._polling = False
        self._on_complete = None
        self._on_error = None
        self._on_object_ready = None
        self._on_download_failed = None
        self._on_bbox_ready = None
        self._phase = ""
        self._downloaded_objects = set()
        self._pending_objects = {}
        self._total_objects = 0
        self._completed_objects = 0
        self._polling_stopped = False
        self._active_downloads = 0
        self._next_import_id = 0
        self._downloaded_glbs = {}
        self._failed_objects = []
        self._consecutive_poll_failures = 0
        self._current_poll_interval = POLL_INTERVAL_PHASE1
        self._timings = {}
        self._set_generating(False, success=success)
        self._tag_redraw()

    def _set_generating(self, generating: bool, success: bool = True):
        """Set the scene-level is_generating flag.

        Args:
            generating: Whether generation is in progress.
            success: When *generating* is False, True triggers the fast-fill
                completion animation; False resets progress to zero.
        """
        try:
            scene = bpy.context.scene
            if scene and hasattr(scene, 'mixie_scene_recon_is_generating'):
                scene.mixie_scene_recon_is_generating = generating
            if not generating:
                if success:
                    from .generate_progress import complete_progress
                    complete_progress('scene_recon')
                else:
                    from .generate_progress import reset_progress
                    reset_progress('scene_recon')
        except Exception:
            pass

    def _set_error(self, error_msg: str):
        """Set error state and clean up."""
        # Update tab error text
        try:
            scene = bpy.context.scene
            if scene and hasattr(scene, 'mixie_moodboard_sidebar'):
                sidebar = scene.mixie_moodboard_sidebar
                if hasattr(sidebar, 'tab_scene_recon'):
                    sidebar.tab_scene_recon.error_text = error_msg
        except Exception:
            pass

        # Call error callback
        if self._on_error:
            try:
                self._on_error(error_msg)
            except Exception as e:
                logger.error("[SceneRecon] Error callback failed: %s", e)

        self._finish_job(success=False)

    def _update_tab_status(
        self,
        stage_name: str = "",
        stage_detail: str = "",
        status_text: str = "",
        elapsed: float = 0.0,
    ):
        """Update tab UI properties with current status."""
        try:
            scene = bpy.context.scene
            if not scene or not hasattr(scene, 'mixie_moodboard_sidebar'):
                return
            sidebar = scene.mixie_moodboard_sidebar
            if not hasattr(sidebar, 'tab_scene_recon'):
                return
            tab = sidebar.tab_scene_recon
            tab.stage_name = stage_name
            tab.stage_detail = stage_detail
            tab.status_text = status_text
            tab.elapsed_seconds = elapsed
            tab.error_text = ""
        except Exception:
            pass
        self._tag_redraw()

    def _update_tab_phase2(
        self,
        phase: str = "",
        total_objects: int = 0,
        completed_objects: int = 0,
        elapsed: float = 0.0,
    ):
        """Update Phase 2-specific tab properties."""
        try:
            scene = bpy.context.scene
            if not scene or not hasattr(scene, 'mixie_moodboard_sidebar'):
                return
            sidebar = scene.mixie_moodboard_sidebar
            if not hasattr(sidebar, 'tab_scene_recon'):
                return
            tab = sidebar.tab_scene_recon
            tab.phase = phase
            tab.total_objects = total_objects
            tab.completed_objects = completed_objects
        except Exception:
            pass

    def _tag_redraw(self):
        """Trigger UI redraw."""
        try:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass

    def clear_all(self) -> None:
        """Stop polling, release every per-object payload, and reset state.

        Called from the module unregister path so a long-lived job does not
        keep its captured ``glb_bytes`` (tens of MB per object) alive past
        Blender shutdown / addon reload.
        """
        self._polling = False
        self._polling_stopped = True
        self._job_id = None
        self._on_complete = None
        self._on_error = None
        self._on_object_ready = None
        self._on_download_failed = None
        self._on_bbox_ready = None
        self._downloaded_objects.clear()
        self._pending_objects.clear()
        self._downloaded_glbs.clear()
        self._failed_objects.clear()
        self._active_downloads = 0
        self._next_import_id = 0
        self._total_objects = 0
        self._completed_objects = 0


# Singleton instance
_scene_recon_manager: Optional[SceneReconManager] = None


def get_scene_recon_manager() -> SceneReconManager:
    """Get or create the global Scene Reconstruction manager instance."""
    global _scene_recon_manager
    if _scene_recon_manager is None:
        _scene_recon_manager = SceneReconManager()
    return _scene_recon_manager
