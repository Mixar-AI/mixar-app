# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Generation Manager for Moodboard

Manages scene generation jobs with polling and progressive downloads.
Uses a singleton pattern to coordinate async operations.
"""

import threading
from typing import Callable, Dict, List, Optional, Set

import bpy
import requests as requests_lib

from mixar.config.logging_config import get_logger
from ...common.api.services.generation_queue_service import get_generation_queue_service
from ...common.api.services.scene_gen_service import get_scene_gen_service
from ...common.api.response import APIResponse

logger = get_logger(__name__)


# Terminal job statuses that indicate polling should stop
TERMINAL_JOB_STATUSES = {
    "completed",
    "partially_completed",
    "failed",
    "cancelled",
    "expired",
}

# Download retry configuration
MAX_DOWNLOAD_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds
RETRY_BACKOFF_MULTIPLIER = 2.0  # exponential backoff


class SceneGenManager:
    """
    Singleton manager for Scene Generation jobs.

    Handles job submission, 1-second polling, and sequential downloads.
    All API calls run in background threads, results processed on main thread.
    Downloads happen sequentially in object_id order.
    """

    def __init__(self):
        # Track active jobs: image_name -> job_id
        self._active_jobs: Dict[str, str] = {}
        # Track downloaded objects per job: job_id -> set of object_ids
        self._downloaded_objects: Dict[str, Set[int]] = {}
        # Track callbacks per job: job_id -> callback function
        self._import_callbacks: Dict[str, Callable] = {}
        # Track image items per job: job_id -> img_item reference
        self._job_image_items: Dict[str, any] = {}
        # Track polling state: job_id -> True if polling
        self._polling_jobs: Dict[str, bool] = {}
        # Track next expected object_id for sequential download: job_id -> next_id
        self._next_object_id: Dict[str, int] = {}
        # Track pending objects waiting to be downloaded: job_id -> {object_id: obj_data}
        self._pending_objects: Dict[str, Dict[int, dict]] = {}
        # Track if currently downloading: job_id -> True if download in progress
        self._downloading: Dict[str, bool] = {}
        # Track terminal status (to finish job after all downloads complete): job_id -> status
        self._terminal_status: Dict[str, str] = {}
        # Lock for download state transitions (prevents race between download start and job finish)
        self._download_lock = threading.Lock()
        # Retry tracking for failed downloads
        self._download_attempts: Dict[str, Dict[int, int]] = {}  # job_id -> {object_id -> attempt_count}
        self._failed_objects: Dict[str, List[tuple]] = {}  # job_id -> [(object_id, error_msg), ...]
        self._error_callbacks: Dict[str, Callable] = {}  # job_id -> on_error callback

    def submit_job(
        self,
        img_item,
        image_bytes: bytes,
        mask_bytes_list: List[bytes],
        on_object_ready: Optional[Callable[[bytes, dict, int], None]] = None,
        on_download_failed: Optional[Callable[[int, str], None]] = None,
        texture_size: int = 1024,
        simplify: float = 0.95,
    ) -> bool:
        """
        Submit a scene generation job and start polling.

        Args:
            img_item: MixieMoodboardImage item
            image_bytes: Compressed image PNG bytes
            mask_bytes_list: List of mask PNG bytes
            on_object_ready: Callback(glb_bytes, pose_data, object_id) for each ready object
            on_download_failed: Callback(object_id, error_msg) for permanent download failures
            texture_size: Texture resolution
            simplify: Mesh simplification ratio

        Returns:
            True if job was submitted, False if already has an active job
        """
        if img_item is None or img_item.image is None:
            logger.error("[SceneGen] No image item provided")
            return False

        image_name = img_item.image.name

        # Check if already has an active job
        if image_name in self._active_jobs:
            logger.warning("[SceneGen] Image '%s' already has an active job", image_name)
            return False

        import base64 as _b64

        payload = {
            "image_bytes_b64": _b64.b64encode(image_bytes).decode(),
            "mask_bytes_list_b64": [_b64.b64encode(m).decode() for m in mask_bytes_list],
            "texture_size": texture_size,
            "simplify": simplify,
        }

        def on_submit_success(response):
            self._handle_submit_response(
                response, img_item, image_name, on_object_ready, on_download_failed
            )

        def on_submit_error(error):
            logger.error("[SceneGen] Job submission failed: %s", error)

        try:
            service = get_generation_queue_service()
            service.enqueue(
                job_type="scene_gen",
                model="scene_gen_v1",
                payload=payload,
                on_success=on_submit_success,
                on_error=on_submit_error,
            )
        except Exception as e:
            logger.error("[SceneGen] Job submission failed: %s", e)
            return False

        logger.debug("[SceneGen] Submitting job for '%s'...", image_name)
        return True

    def _handle_submit_response(
        self,
        response: APIResponse,
        img_item,
        image_name: str,
        on_object_ready: Optional[Callable],
        on_download_failed: Optional[Callable],
    ):
        """Handle job submission response on main thread."""
        if not response.success:
            logger.error("[SceneGen] Job submission failed: %s", response.message)
            return

        data = response.data or {}
        logger.debug("[SceneGen] Submit response received")

        # Response structure: {status, message, data: {job_id, ...}}
        inner_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        job_id = inner_data.get("job_id") or data.get("job_id")

        if not job_id:
            logger.error("[SceneGen] No job_id in response")
            return

        # Store job state
        self._active_jobs[image_name] = job_id
        self._downloaded_objects[job_id] = set()
        self._job_image_items[job_id] = img_item
        self._next_object_id[job_id] = 0  # Start expecting object 0
        self._pending_objects[job_id] = {}  # Queue for out-of-order objects
        self._downloading[job_id] = False  # Not currently downloading
        self._download_attempts[job_id] = {}  # Track retry attempts per object
        self._failed_objects[job_id] = []  # Track permanently failed objects
        if on_object_ready:
            self._import_callbacks[job_id] = on_object_ready
        if on_download_failed:
            self._error_callbacks[job_id] = on_download_failed

        # Store job_id in image properties
        img_item.scene_gen_job_id = job_id

        # Set scene-level is_generating flag for UI
        scene = bpy.context.scene
        if scene and hasattr(scene, 'mixie_segment_to_3d_is_generating'):
            scene.mixie_segment_to_3d_is_generating = True

        from .generate_progress import start_progress
        start_progress('segment_to_3d')

        total_objects = inner_data.get('total_objects') or data.get('total_objects', 'unknown')
        logger.debug("[SceneGen] Job submitted for '%s'", image_name)
        logger.debug("[SceneGen] Total objects: %s", total_objects)

        # Start polling
        self._start_polling(job_id)

    def _start_polling(self, job_id: str):
        """Start 1-second polling timer for job status."""
        self._polling_jobs[job_id] = True

        def poll_timer():
            return self._poll_job(job_id)

        # Register timer with 1 second interval
        bpy.app.timers.register(poll_timer, first_interval=1.0)
        logger.debug("[SceneGen] Started polling for job")

    def _poll_job(self, job_id: str) -> Optional[float]:
        """
        Poll job status. Called by bpy.app.timers.

        Returns:
            1.0 to continue polling in 1 second, None to stop
        """
        # Check if still polling
        if not self._polling_jobs.get(job_id, False):
            return None

        # Poll in background thread
        def fetch_status():
            try:
                service = get_generation_queue_service()
                response = service.get_job_status_sync(job_id)

                def handle_status():
                    self._handle_gq_status_response(job_id, response)
                    return None

                bpy.app.timers.register(handle_status, first_interval=0.0)

            except Exception as e:
                error_msg = str(e)
                is_not_found = "not found" in error_msg.lower() or "404" in error_msg
                if is_not_found:
                    self._polling_jobs[job_id] = False

                def report_error():
                    logger.error("[SceneGen] Status poll failed: %s", error_msg)
                    return None

                bpy.app.timers.register(report_error, first_interval=0.0)

        thread = threading.Thread(target=fetch_status, daemon=True)
        thread.start()

        # Continue polling
        return 1.0

    # Generation queue status → scene gen status mapping
    _GQ_STATUS_MAP = {
        "PENDING": "pending",
        "SUBMITTED": "processing",
        "POLLING": "processing",
        "DONE": "completed",
        "FAILED": "failed",
        "CANCELLED": "cancelled",
    }

    def _handle_gq_status_response(self, job_id: str, response: APIResponse):
        """Unwrap generation queue envelope and delegate to status handler."""
        if not response.success:
            logger.warning("[SceneGen] Status check failed: %s", response.message)
            return

        data = response.data or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        if not isinstance(inner, dict):
            return

        gq_status = inner.get("status", "")
        result = inner.get("result") or {}

        if gq_status == "DONE" and isinstance(result, dict):
            # Pass through the scene gen result data
            mapped = dict(result)
            if "status" not in mapped:
                mapped["status"] = "completed"
            unwrapped = APIResponse(
                success=True, status_code=response.status_code,
                message=response.message, data=mapped,
            )
        elif gq_status in ("FAILED", "CANCELLED", "DLQ"):
            error = inner.get("error", "Job failed")
            unwrapped = APIResponse(
                success=True, status_code=response.status_code,
                message=response.message,
                data={"status": "failed", "error": error},
            )
        else:
            mapped_status = self._GQ_STATUS_MAP.get(gq_status, "pending")
            unwrapped = APIResponse(
                success=True, status_code=response.status_code,
                message=response.message,
                data={"status": mapped_status},
            )

        self._handle_status_response(job_id, unwrapped)

    def _handle_status_response(self, job_id: str, response: APIResponse):
        """Handle job status response on main thread."""
        if not response.success:
            logger.warning("[SceneGen] Status check failed: %s", response.message)
            return

        data = response.data or {}

        # Response structure: {status, message, data: {job_id, status, objects, ...}}
        inner_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        job_status = inner_data.get("status") or data.get("status", "")
        objects = inner_data.get("objects") or data.get("objects", [])

        logger.debug("[SceneGen] Job status: %s", job_status)

        # Log error details if job failed
        if job_status == "failed":
            error_message = inner_data.get("error") or inner_data.get("message") or data.get("message") or "Unknown error"
            logger.error("[SceneGen] Job FAILED: %s", error_message)
            # Store error for callback
            if job_id not in self._failed_objects:
                self._failed_objects[job_id] = []
            self._failed_objects[job_id].append((-1, f"Job failed: {error_message}"))

        # Queue completed objects (don't download yet)
        downloaded = self._downloaded_objects.get(job_id, set())
        pending = self._pending_objects.get(job_id, {})

        for obj in objects:
            object_id = obj.get("object_id")
            obj_status = obj.get("status", "")
            download_token = obj.get("download_token")

            # Skip if not completed or already downloaded/pending
            if obj_status != "completed":
                continue
            if object_id in downloaded:
                continue
            if object_id in pending:
                continue
            download_url = obj.get("download_url")
            if not download_token and not download_url:
                continue

            # Queue this object for download
            pending[object_id] = obj
            logger.debug("[SceneGen] Queued object %s for download", object_id)

        self._pending_objects[job_id] = pending

        # Store terminal status for later (don't finish yet if downloads pending)
        if job_status in TERMINAL_JOB_STATUSES:
            self._terminal_status[job_id] = job_status
            # Stop polling - no more objects will complete
            self._polling_jobs[job_id] = False
            logger.debug("[SceneGen] Job reached terminal status '%s', stopping polls", job_status)

        # Try to start next sequential download
        self._try_download_next(job_id)

        # Check if job should finish (all downloads complete)
        self._try_finish_job(job_id)

    def _try_download_next(self, job_id: str):
        """Try to download the next object in sequence."""
        obj_data = None

        with self._download_lock:
            # Don't start if already downloading
            if self._downloading.get(job_id, False):
                return

            next_id = self._next_object_id.get(job_id, 0)
            pending = self._pending_objects.get(job_id, {})

            # Check if next object is ready
            if next_id not in pending:
                return

            # Set downloading flag and pop atomically (under lock)
            self._downloading[job_id] = True
            obj_data = pending.pop(next_id)
            self._pending_objects[job_id] = pending

        # Start download (outside lock - it's a long operation)
        self._download_object(job_id, obj_data)

    def _try_finish_job(self, job_id: str):
        """Finish job only if terminal status reached and all downloads complete."""
        with self._download_lock:
            # Check if we have a terminal status
            final_status = self._terminal_status.get(job_id)
            if not final_status:
                return

            # Check if still downloading
            if self._downloading.get(job_id, False):
                return

            # Check if there are pending objects
            pending = self._pending_objects.get(job_id, {})
            if pending:
                return

            # All done, finish the job (inside lock to prevent new downloads starting)
            self._finish_job(job_id, final_status)

    def _download_object(self, job_id: str, obj_data: dict):
        """Download a completed object in background thread."""
        object_id = obj_data.get("object_id")
        download_token = obj_data.get("download_token")
        download_url = obj_data.get("download_url")
        pose_data = obj_data.get("pose")

        logger.debug("[SceneGen] Downloading object %s...", object_id)

        # Note: _downloading flag is already set by _try_download_next before calling this

        # Mark as downloaded to prevent re-queuing
        downloaded = self._downloaded_objects.get(job_id, set())
        downloaded.add(object_id)
        self._downloaded_objects[job_id] = downloaded

        def download_api_call():
            try:
                if download_url:
                    # GPU queue path: download directly from S3 presigned URL
                    raw_resp = requests_lib.get(download_url, timeout=120)
                    raw_resp.raise_for_status()
                    response = APIResponse(
                        success=True,
                        status_code=200,
                        message="OK",
                        data={},
                        raw=raw_resp,
                    )
                else:
                    # Direct path: download via backend proxy
                    service = get_scene_gen_service()
                    response = service.download_object(job_id, download_token)

                def handle_download():
                    self._handle_download_response(job_id, response, pose_data, object_id, download_token, download_url)
                    return None

                bpy.app.timers.register(handle_download, first_interval=0.0)

            except Exception as e:
                error_msg = str(e)

                def handle_exception():
                    # Get current attempt count
                    attempts = self._download_attempts.get(job_id, {})
                    current_attempt = attempts.get(object_id, 0) + 1
                    attempts[object_id] = current_attempt
                    self._download_attempts[job_id] = attempts

                    # Clear downloading flag
                    with self._download_lock:
                        self._downloading[job_id] = False

                    # Remove from downloaded so it can be retried
                    if job_id in self._downloaded_objects:
                        self._downloaded_objects[job_id].discard(object_id)

                    if current_attempt < MAX_DOWNLOAD_RETRIES:
                        delay = RETRY_BASE_DELAY * (RETRY_BACKOFF_MULTIPLIER ** (current_attempt - 1))
                        logger.warning("[SceneGen] Download exception for object %s, retrying in %.1fs", object_id, delay)
                        self._retry_download(
                            job_id,
                            {"object_id": object_id, "download_token": download_token, "download_url": download_url, "pose": pose_data},
                            delay,
                        )
                    else:
                        logger.error("[SceneGen] Permanent failure for object %s: %s", object_id, error_msg)
                        self._handle_permanent_failure(job_id, object_id, error_msg)
                    return None

                bpy.app.timers.register(handle_exception, first_interval=0.0)

        thread = threading.Thread(target=download_api_call, daemon=True)
        thread.start()

    def _retry_download(self, job_id: str, obj_data: dict, delay: float):
        """Schedule a retry download after delay."""
        object_id = obj_data.get("object_id")

        def do_retry():
            # Re-queue the object for download
            with self._download_lock:
                pending = self._pending_objects.get(job_id, {})
                pending[object_id] = obj_data
                self._pending_objects[job_id] = pending

            # Try to download (will be picked up if not already downloading)
            self._try_download_next(job_id)
            return None

        bpy.app.timers.register(do_retry, first_interval=delay)

    def _handle_permanent_failure(self, job_id: str, object_id: int, error_msg: str):
        """Handle a permanently failed download."""
        # Track failed object
        if job_id not in self._failed_objects:
            self._failed_objects[job_id] = []
        self._failed_objects[job_id].append((object_id, error_msg))

        # Notify via callback
        callback = self._error_callbacks.get(job_id)
        if callback:
            try:
                callback(object_id, error_msg)
            except Exception as e:
                logger.error("[SceneGen] Error callback failed: %s", e)

        # Move to next object
        self._next_object_id[job_id] = object_id + 1
        self._try_download_next(job_id)
        self._try_finish_job(job_id)

    def _handle_download_response(
        self,
        job_id: str,
        response: APIResponse,
        pose_data: Optional[dict],
        object_id: int,
        download_token: str,
        download_url: Optional[str] = None,
    ):
        """Handle download response on main thread."""
        # Clear downloading flag (under lock to synchronize with _try_finish_job)
        with self._download_lock:
            self._downloading[job_id] = False

        if not response.success:
            logger.error("[SceneGen] Download failed: %s", response.message)

            # Get current attempt count
            attempts = self._download_attempts.get(job_id, {})
            current_attempt = attempts.get(object_id, 0) + 1
            attempts[object_id] = current_attempt
            self._download_attempts[job_id] = attempts

            # Remove from downloaded so it can be retried
            if job_id in self._downloaded_objects:
                self._downloaded_objects[job_id].discard(object_id)

            if current_attempt < MAX_DOWNLOAD_RETRIES:
                # Calculate backoff delay
                delay = RETRY_BASE_DELAY * (RETRY_BACKOFF_MULTIPLIER ** (current_attempt - 1))
                logger.warning("[SceneGen] Retrying object %s in %.1fs (attempt %s/%s)", object_id, delay, current_attempt + 1, MAX_DOWNLOAD_RETRIES)

                # Re-queue for retry
                obj_data = {
                    "object_id": object_id,
                    "download_token": download_token,
                    "download_url": download_url,
                    "pose": pose_data,
                }
                self._retry_download(job_id, obj_data, delay)
            else:
                # Permanent failure after max retries
                error_msg = f"Failed after {MAX_DOWNLOAD_RETRIES} attempts: {response.message}"
                logger.error("[SceneGen] Permanent failure for object %s: %s", object_id, error_msg)
                self._handle_permanent_failure(job_id, object_id, error_msg)
            return

        # Get GLB bytes from raw response
        glb_bytes = None
        if response.raw is not None:
            glb_bytes = response.raw.content

        if not glb_bytes:
            logger.error("[SceneGen] No GLB data received for object %s", object_id)
            # Move to next object
            self._next_object_id[job_id] = object_id + 1
            self._try_download_next(job_id)
            return

        logger.debug("[SceneGen] Downloaded object %s: %s bytes", object_id, len(glb_bytes))

        # Call import callback
        callback = self._import_callbacks.get(job_id)
        if callback:
            try:
                callback(glb_bytes, pose_data, object_id)
            except Exception as e:
                logger.error("[SceneGen] Import callback failed: %s", e)

        # Move to next object in sequence
        self._next_object_id[job_id] = object_id + 1

        # Try to download next object
        self._try_download_next(job_id)

        # Check if job should finish (all downloads complete)
        self._try_finish_job(job_id)

    def _finish_job(self, job_id: str, final_status: str):
        """Clean up after job completion."""
        logger.debug("[SceneGen] Job finished with status: %s", final_status)

        # Stop polling
        self._polling_jobs[job_id] = False

        # Find and clean up image item reference
        image_name = None
        for name, jid in self._active_jobs.items():
            if jid == job_id:
                image_name = name
                break

        if image_name:
            del self._active_jobs[image_name]

        # Clear scene-level is_generating flag if no more active jobs
        if not self._active_jobs:
            scene = bpy.context.scene
            if scene and hasattr(scene, 'mixie_segment_to_3d_is_generating'):
                scene.mixie_segment_to_3d_is_generating = False

            from .generate_progress import complete_progress, reset_progress
            if final_status in ("completed", "partially_completed"):
                complete_progress('segment_to_3d')
            else:
                reset_progress('segment_to_3d')

        # Log error details if job failed
        if final_status == "failed":
            failed_objects = self._failed_objects.get(job_id, [])
            if failed_objects:
                error_messages = [msg for _, msg in failed_objects]
                logger.error("[SceneGen] Job failed with errors: %s", '; '.join(error_messages))
            else:
                logger.error("[SceneGen] Job failed (no error details available)")

        # Clear job-specific data
        self._downloaded_objects.pop(job_id, None)
        self._import_callbacks.pop(job_id, None)
        self._job_image_items.pop(job_id, None)
        self._polling_jobs.pop(job_id, None)
        self._next_object_id.pop(job_id, None)
        self._pending_objects.pop(job_id, None)
        self._downloading.pop(job_id, None)
        self._terminal_status.pop(job_id, None)
        self._download_attempts.pop(job_id, None)
        self._failed_objects.pop(job_id, None)
        self._error_callbacks.pop(job_id, None)

        # Trigger UI redraw
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

    def cancel_job(self, image_name: str) -> bool:
        """
        Cancel an active job for an image.

        Args:
            image_name: Name of the image

        Returns:
            True if job was cancelled, False if no active job
        """
        job_id = self._active_jobs.get(image_name)
        if not job_id:
            return False

        # Stop polling immediately
        self._polling_jobs[job_id] = False

        # Cancel on server in background
        def cancel_api_call():
            try:
                service = get_generation_queue_service()
                service.cancel_job(job_id)
                logger.debug("[SceneGen] Cancelled job")
            except Exception as e:
                logger.error("[SceneGen] Failed to cancel job: %s", e)

        thread = threading.Thread(target=cancel_api_call, daemon=True)
        thread.start()

        # Clean up local state
        self._finish_job(job_id, "cancelled")
        return True

    def get_status(self, image_name: str) -> Optional[str]:
        """
        Get current job status for an image.

        Args:
            image_name: Name of the image

        Returns:
            Job ID if active, None if no active job
        """
        return self._active_jobs.get(image_name)

    def is_generating(self, image_name: str) -> bool:
        """Check if image has an active generation job."""
        return image_name in self._active_jobs

    def has_active_jobs(self) -> bool:
        """Check if any generation jobs are currently active."""
        return len(self._active_jobs) > 0

    def clear_all(self):
        """Clear all tracking data and stop all polling."""
        # Stop all polling
        for job_id in list(self._polling_jobs.keys()):
            self._polling_jobs[job_id] = False

        self._active_jobs.clear()
        self._downloaded_objects.clear()
        self._import_callbacks.clear()
        self._job_image_items.clear()
        self._polling_jobs.clear()
        self._next_object_id.clear()
        self._pending_objects.clear()
        self._downloading.clear()
        self._terminal_status.clear()
        self._download_attempts.clear()
        self._failed_objects.clear()
        self._error_callbacks.clear()


# Singleton instance
_scene_gen_manager: Optional[SceneGenManager] = None


def get_scene_gen_manager() -> SceneGenManager:
    """Get or create the global Scene Generation manager instance."""
    global _scene_gen_manager
    if _scene_gen_manager is None:
        _scene_gen_manager = SceneGenManager()
    return _scene_gen_manager
