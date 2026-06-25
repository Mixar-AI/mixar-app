# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mesh Segment Manager Module (DEPRECATED).

Superseded by ``mesh_segment_queue.py`` which uses the unified FeatureQueue
framework. This module is kept for reference; new code should use
``enqueue_mesh_segment_job()`` from ``mesh_segment_queue`` instead.
"""

import bpy
import threading
from typing import Callable, Dict, Optional

from mixar.config.logging_config import get_logger
from ...common.api.services.generation_queue_service import get_generation_queue_service
from .mesh_labeler import apply_labels_to_mesh

logger = get_logger(__name__)


class MeshSegmentManager:
    """
    Manages mesh segment job lifecycle including polling and result handling.

    Singleton class that tracks the current mesh segment job and handles
    status polling via Blender timers with background thread API calls.
    """

    POLL_INTERVAL = 2.0  # seconds
    CHECK_INTERVAL = 0.1  # seconds to check for thread completion

    def __init__(self):
        self._job_id: Optional[str] = None
        self._mesh_object: Optional[bpy.types.Object] = None
        self._polling: bool = False
        self._on_status_update: Optional[Callable[[str, float, str], None]] = None
        self._on_complete: Optional[Callable[[Dict], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        # Thread-safe result storage
        self._poll_result: Dict = {"done": False, "response": None, "error": None}
        self._poll_thread: Optional[threading.Thread] = None

    @property
    def job_id(self) -> Optional[str]:
        """Current job ID."""
        return self._job_id

    @property
    def is_processing(self) -> bool:
        """Check if a job is currently being processed."""
        return self._job_id is not None and self._polling

    def submit_job(
        self,
        mesh_object: bpy.types.Object,
        mesh_file_path: str,
        description: str,
        expected_parts: str,
        on_status_update: Optional[Callable[[str, float, str], None]] = None,
        on_complete: Optional[Callable[[Dict], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Submit a segmentation job (synchronous).

        Args:
            mesh_object: The Blender mesh object being segmented
            mesh_file_path: Path to the exported OBJ file
            description: Description of the mesh
            expected_parts: Comma-separated expected parts
            on_status_update: Callback(status, progress, current_step)
            on_complete: Callback(result_dict) when job completes
            on_error: Callback(error_message) on error

        Returns:
            True if job was submitted successfully, False otherwise
        """
        if self.is_processing:
            if on_error:
                on_error("A mesh segment job is already in progress")
            return False

        self._mesh_object = mesh_object
        self._on_status_update = on_status_update
        self._on_complete = on_complete
        self._on_error = on_error

        import base64 as _b64

        try:
            with open(mesh_file_path, "rb") as f:
                mesh_bytes = f.read()
        except Exception as e:
            self._handle_error(f"Failed to read mesh file: {e}")
            return False

        payload = {
            "mesh_file_bytes_b64": _b64.b64encode(mesh_bytes).decode(),
            "mesh_filename": "mesh.obj",
            "description": description,
            "expected_parts": expected_parts,
        }

        try:
            service = get_generation_queue_service()
            submit_response = service.post(
                "enqueue",
                json={
                    "job_type": "mesh_segment",
                    "model": "mesh_segment_v1",
                    "payload": payload,
                    "idempotency_key": __import__("uuid").uuid4().hex,
                },
            )

            if not submit_response.success:
                self._handle_error(submit_response.message or "Failed to submit job")
                return False

            data = submit_response.data or {}
            inner_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
            self._job_id = inner_data.get("job_id") or data.get("job_id")

            if not self._job_id:
                self._handle_error(f"No job_id in response: {data}")
                return False

            logger.debug("[MeshSegment] Job submitted: %s", self._job_id)

            scene = bpy.context.scene
            scene.mixie_mesh_segment_job_id = self._job_id
            scene.mixie_mesh_segment_status = "pending"
            scene.mixie_mesh_segment_is_processing = True
            scene.mixie_mesh_segment_error = ""

            from mixar.modules.moodboard.core.generate_progress import start_progress
            start_progress('mesh_segment')

            self._start_polling()
            return True

        except Exception as e:
            self._handle_error(f"Submit failed: {e}")
            return False

    def _start_polling(self) -> None:
        """Start the status polling timer."""
        if self._polling:
            return
        self._polling = True
        bpy.app.timers.register(
            self._poll_status,
            first_interval=self.POLL_INTERVAL,
        )

    def _stop_polling(self) -> None:
        """Stop the status polling timer."""
        self._polling = False
        try:
            if bpy.app.timers.is_registered(self._poll_status):
                bpy.app.timers.unregister(self._poll_status)
        except (ValueError, RuntimeError):
            pass

    def _poll_status_thread(self, job_id: str) -> None:
        """Background thread to call status API via generation queue."""
        try:
            service = get_generation_queue_service()
            response = service.get_job_status_sync(job_id)
            self._poll_result = {"done": True, "response": response, "error": None}
        except Exception as e:
            self._poll_result = {"done": True, "response": None, "error": str(e)}

    def _poll_status(self) -> Optional[float]:
        """Timer callback to poll job status (non-blocking with background thread)."""
        if not self._polling or not self._job_id:
            return None

        # Check if a poll thread is running
        if self._poll_thread and self._poll_thread.is_alive():
            # Thread still running, check again soon
            return self.CHECK_INTERVAL

        # Check if we have a result from previous thread
        if self._poll_result["done"]:
            # Process the result
            result = self._process_poll_result()
            if result is None:
                return None  # Stop polling (completed or failed)
            # Reset and schedule next poll
            self._poll_result = {"done": False, "response": None, "error": None}
            return self.POLL_INTERVAL

        # Start a new background thread for the API call
        self._poll_result = {"done": False, "response": None, "error": None}
        self._poll_thread = threading.Thread(
            target=self._poll_status_thread,
            args=(self._job_id,),
            daemon=True
        )
        self._poll_thread.start()

        # Check for result soon
        return self.CHECK_INTERVAL

    def _process_poll_result(self) -> Optional[float]:
        """Process the result from the background poll thread. Returns None to stop polling."""
        if self._poll_result["error"]:
            logger.error("[MeshSegment] Poll error: %s", self._poll_result['error'])
            return self.POLL_INTERVAL

        response = self._poll_result["response"]
        if not response:
            return self.POLL_INTERVAL

        if not response.success:
            logger.error("[MeshSegment] Status error: %s", response.message)
            return self.POLL_INTERVAL

        data = response.data or {}
        inner_data = data.get("data", data) if isinstance(data, dict) else {}
        if not isinstance(inner_data, dict):
            return self.POLL_INTERVAL

        # Map generation queue statuses
        gq_status = inner_data.get("status", "")
        result = inner_data.get("result") or {}

        # Map to mesh segment status
        if gq_status == "PENDING":
            status = "pending"
            progress = 0.0
            current_step = "Queued"
        elif gq_status in ("SUBMITTED", "POLLING"):
            status = "processing"
            progress = inner_data.get("progress", 0.5) or 0.5
            current_step = "Processing..."
        elif gq_status == "DONE":
            status = "completed"
            progress = 1.0
            current_step = "Complete"
        elif gq_status == "FAILED":
            status = "failed"
            progress = 0.0
            current_step = ""
        else:
            status = "pending"
            progress = 0.0
            current_step = ""

        logger.debug("[MeshSegment] Status: %s (gq: %s)", status, gq_status)

        scene = bpy.context.scene
        scene.mixie_mesh_segment_status = status
        scene.mixie_mesh_segment_progress = progress
        scene.mixie_mesh_segment_current_step = current_step

        if self._on_status_update:
            self._on_status_update(status, progress, current_step)

        if status == "completed":
            # Extract result directly from poll response (no separate fetch)
            self._handle_inline_result(result)
            return None
        elif status == "failed":
            error_msg = inner_data.get("error", "Mesh segment job failed")
            self._handle_error(error_msg)
            return None

        for area in bpy.context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()

        return self.POLL_INTERVAL

    def _handle_inline_result(self, result: Dict) -> None:
        """Handle result extracted inline from the generation queue poll response."""
        self._stop_polling()

        island_labels = result.get("island_labels", {})
        if not island_labels:
            self._handle_error("No island labels in result")
            return

        logger.debug("[MeshSegment] Result received with %d island labels", len(island_labels))

        # Apply labels to mesh
        if self._mesh_object:
            try:
                count, labels = apply_labels_to_mesh(self._mesh_object, island_labels)
                logger.debug("[MeshSegment] Applied %d vertex groups to mesh", count)
            except Exception as e:
                logger.error("[MeshSegment] Error applying labels: %s", e)

        # Update scene properties
        scene = bpy.context.scene
        scene.mixie_mesh_segment_is_processing = False
        scene.mixie_mesh_segment_status = "completed"

        from mixar.modules.moodboard.core.generate_progress import complete_progress
        complete_progress('mesh_segment')

        # Store result for UI display
        scene.mixie_mesh_segment_result = str(island_labels)

        # Notify callback
        if self._on_complete:
            self._on_complete(result)

        # Cleanup
        self._cleanup()

        # Force UI redraw
        for area in bpy.context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()

    def _handle_error(self, message: str) -> None:
        """Handle error and cleanup."""
        logger.error("[MeshSegment] Error: %s", message)

        self._stop_polling()

        # Update scene properties
        scene = bpy.context.scene
        scene.mixie_mesh_segment_is_processing = False
        scene.mixie_mesh_segment_error = message

        from mixar.modules.moodboard.core.generate_progress import reset_progress
        reset_progress('mesh_segment')

        # Notify callback
        if self._on_error:
            self._on_error(message)

        self._cleanup()

        # Force UI redraw
        for area in bpy.context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()

    def _cleanup(self) -> None:
        """Clean up after job completion or error."""
        self._job_id = None
        self._mesh_object = None
        self._on_status_update = None
        self._on_complete = None
        self._on_error = None
        self._poll_result = {"done": False, "response": None, "error": None}
        self._poll_thread = None

    def cancel_job(self) -> None:
        """Cancel the current job."""
        if not self._job_id:
            return

        job_id = self._job_id
        self._stop_polling()

        service = get_generation_queue_service()
        try:
            service.cancel_job(job_id)
            logger.debug("[MeshSegment] Job %s cancelled", job_id)
        except Exception as e:
            logger.error("[MeshSegment] Cancel error: %s", e)

        # Update scene properties
        scene = bpy.context.scene
        scene.mixie_mesh_segment_is_processing = False
        scene.mixie_mesh_segment_status = "cancelled"
        scene.mixie_mesh_segment_job_id = ""

        from mixar.modules.moodboard.core.generate_progress import reset_progress
        reset_progress('mesh_segment')

        self._cleanup()

        # Force UI redraw
        for area in bpy.context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()


# Singleton instance
_mesh_segment_manager: Optional[MeshSegmentManager] = None


def get_mesh_segment_manager() -> MeshSegmentManager:
    """Get the global MeshSegmentManager instance."""
    global _mesh_segment_manager
    if _mesh_segment_manager is None:
        _mesh_segment_manager = MeshSegmentManager()
    return _mesh_segment_manager
