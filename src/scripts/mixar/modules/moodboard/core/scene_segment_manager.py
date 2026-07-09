# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Segment Manager for Moodboard

Manages Scene Segment (SAM3) job state, polling, and mask downloads.
Coordinates async operations for the Magic Select tool.
"""

import os
import re
import tempfile
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import bpy

from mixar.config.logging_config import get_logger
from ...common.api.services.scene_segment_service import get_scene_segment_service
from ...common.api.response import APIResponse
from ...common.utils.image_compression_config import get_compression_settings

logger = get_logger(__name__)


class JobStatus(Enum):
    """Status of a scene segment job."""
    PENDING = "pending"
    UPLOADING = "uploading"
    READY = "ready"  # Upload complete, job_id available
    FAILED = "failed"


class RequestStatus(Enum):
    """Status of a segmentation request within a job."""
    QUEUED = "queued"
    GENERATING = "generating"
    COMPLETED = "completed"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"


@dataclass
class SegmentRequest:
    """Tracks a single segmentation request."""
    request_id: str
    status: RequestStatus = RequestStatus.QUEUED
    mask_bytes: Optional[bytes] = None
    error: Optional[str] = None
    callback: Optional[Callable[[bool, Optional[bytes], str], None]] = None


@dataclass
class JobState:
    """Tracks state for a single image's job."""
    job_id: Optional[str] = None
    status: JobStatus = JobStatus.PENDING
    image_size: Optional[Dict[str, int]] = None
    expires_at: Optional[float] = None  # UTC timestamp
    requests: Dict[str, SegmentRequest] = field(default_factory=dict)
    upload_callback: Optional[Callable[[bool, str], None]] = None


def _compress_image_for_scene_segment(image: bpy.types.Image, img_item=None) -> bytes:
    """Compress and cache a Blender image for Scene Segment upload.

    Compression parameters (max resolution, JPEG quality) are read from the
    centralized per-service config (``"scene_segment"`` entry in
    :mod:`mixar.modules.common.utils.image_compression_config`).

    If *img_item* is provided the compressed Blender image copy is stored in
    ``img_item.compressed_image`` for potential reuse.

    Args:
        image:    The source Blender image.
        img_item: Optional moodboard image property group.

    Returns:
        JPEG-compressed bytes ready for upload.
    """
    settings = get_compression_settings("scene_segment")
    width, height = image.size

    # Calculate new dimensions preserving aspect ratio
    max_dim = max(width, height)
    if max_dim > settings.max_dimension:
        scale = settings.max_dimension / max_dim
        new_width = int(width * scale)
        new_height = int(height * scale)
    else:
        new_width, new_height = width, height

    # Remove stale compressed image stored on img_item (if any)
    if img_item and img_item.compressed_image:
        try:
            old_compressed = img_item.compressed_image
            img_item.compressed_image = None
            bpy.data.images.remove(old_compressed)
        except Exception:
            pass

    # Create a working copy so the original is never modified
    compressed_name = f"{image.name}_compressed"
    compressed_image = image.copy()
    compressed_image.name = compressed_name

    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, f"_scene_segment_upload_{image.name}.jpg")

    # Track success so the cleanup path knows whether to keep the copy
    # (handed off to img_item via .pack()) or release it (any failure
    # between .copy() and assignment used to leak the datablock).
    handed_off = False
    try:
        if new_width != width or new_height != height:
            compressed_image.scale(new_width, new_height)
            logger.debug("[SceneSegment] Resized %sx%s -> %sx%s", width, height, new_width, new_height)

        compressed_image.file_format = 'JPEG'
        compressed_image.save_render(temp_path)

        # Update filepath before pack() so Blender can read the file
        # (fixes issues with images that have deleted temp filepaths, e.g. Imagegen images)
        compressed_image.filepath = temp_path
        compressed_image.source = 'FILE'

        with open(temp_path, 'rb') as f:
            compressed_bytes = f.read()

        if img_item:
            img_item.compressed_image = compressed_image
            compressed_image.pack()
            handed_off = True

        original_size = width * height * 4
        logger.debug(
            "[SceneSegment] Compressed image: ~%sKB -> %sKB (max_dim=%s quality=%s)",
            original_size // 1024, len(compressed_bytes) // 1024,
            settings.max_dimension, settings.quality,
        )
        return compressed_bytes
    finally:
        if not handed_off:
            try:
                bpy.data.images.remove(compressed_image)
            except (RuntimeError, ReferenceError):
                pass
        try:
            os.unlink(temp_path)
        except OSError:
            pass


class SceneSegmentManager:
    """
    Singleton manager for Scene Segment (SAM3) API.

    Handles:
    - Job tracking per image (job_id, status)
    - Request tracking per segmentation (request_id, status)
    - Automatic polling for request completion
    - Mask download coordination
    """

    def __init__(self):
        # Track job state by image name
        self._jobs: Dict[str, JobState] = {}
        # Track pending API request IDs for cancellation
        self._pending_api_requests: Dict[str, str] = {}
        # Polling timer state
        self._poll_timer_running: bool = False
        # Poll interval in seconds
        self._poll_interval: float = 0.5
        # Single reentrant lock for all job/state access (avoids nested lock deadlocks)
        self._jobs_lock = threading.RLock()

    # ========================================================================
    # STATUS CHECKS
    # ========================================================================

    def get_job_state(self, image: bpy.types.Image) -> Optional[JobState]:
        """Get job state for an image."""
        if image is None:
            return None
        with self._jobs_lock:
            return self._jobs.get(image.name)

    def is_ready(self, image: bpy.types.Image) -> bool:
        """Check if image has been uploaded and job is ready."""
        if image is None:
            return False
        with self._jobs_lock:
            state = self._jobs.get(image.name)
            return state is not None and state.status == JobStatus.READY

    def is_uploading(self, image: bpy.types.Image) -> bool:
        """Check if image is currently being uploaded."""
        if image is None:
            return False
        with self._jobs_lock:
            state = self._jobs.get(image.name)
            return state is not None and state.status == JobStatus.UPLOADING

    def get_job_id(self, image: bpy.types.Image) -> Optional[str]:
        """Get job_id for an uploaded image."""
        if image is None:
            return None
        with self._jobs_lock:
            state = self._jobs.get(image.name)
            return state.job_id if state else None

    # ========================================================================
    # UPLOAD
    # ========================================================================

    def queue_upload(
        self,
        image: bpy.types.Image,
        img_item=None,
        on_complete: Optional[Callable[[bool, str], None]] = None,
    ) -> bool:
        """
        Queue an image for upload to Scene Segment API.

        Args:
            image: Blender image to upload
            img_item: Optional MixieMoodboardImageItem for compressed image storage
            on_complete: Callback(success: bool, message: str)

        Returns:
            True if upload was queued, False if already ready/uploading
        """
        if image is None:
            if on_complete:
                on_complete(False, "No image provided")
            return False

        image_name = image.name

        # Check and create state under lock
        with self._jobs_lock:
            state = self._jobs.get(image_name)

            # Skip if already ready (unless expired)
            if state and state.status == JobStatus.READY:
                if state.expires_at and time.time() > (state.expires_at - 300):
                    logger.debug("[SceneSegment] Job expired for '%s', re-uploading", image_name)
                    state.status = JobStatus.PENDING
                    state.job_id = None
                    state.expires_at = None
                    # Fall through to re-upload
                else:
                    if on_complete:
                        on_complete(True, "Already uploaded")
                    return False

            # Skip if uploading, but store callback
            if state and state.status == JobStatus.UPLOADING:
                with self._jobs_lock:
                    if on_complete:
                        state.upload_callback = on_complete
                return False

            # Create new job state
            state = JobState(status=JobStatus.UPLOADING)
            state.upload_callback = on_complete
            self._jobs[image_name] = state

        # Compress image
        try:
            image_bytes = _compress_image_for_scene_segment(image, img_item)
        except Exception as e:
            state.status = JobStatus.FAILED
            self._notify_upload_callback(image_name, False, f"Compression failed: {e}")
            return False

        # Upload asynchronously
        service = get_scene_segment_service()

        def on_success(response: APIResponse):
            # Extract data from nested response structure
            data = response.data or {}
            inner_data = data.get("data", data)
            job_id = inner_data.get("job_id")

            with self._jobs_lock:
                if not job_id:
                    state.status = JobStatus.FAILED
                    self._pending_api_requests.pop(image_name, None)
                    self._notify_upload_callback(image_name, False, "No job_id in response")
                    return

                state.job_id = job_id
                state.status = JobStatus.READY
                state.image_size = inner_data.get("image_size")
                # Parse expires_at from response
                expires_at_str = inner_data.get("expires_at")
                if expires_at_str:
                    try:
                        dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                        state.expires_at = dt.timestamp()
                    except (ValueError, AttributeError):
                        state.expires_at = None
                self._pending_api_requests.pop(image_name, None)

            self._notify_upload_callback(image_name, True, "Upload successful")
            logger.debug("[SceneSegment] Uploaded '%s'", image_name)

        def on_error(error: Exception):
            with self._jobs_lock:
                state.status = JobStatus.FAILED
                self._pending_api_requests.pop(image_name, None)
            self._notify_upload_callback(image_name, False, str(error))
            logger.error("[SceneSegment] Upload failed for '%s': %s", image_name, error)

        request_id = service.upload_image_async(
            image_bytes=image_bytes,
            filename=f"{image_name}.jpg",
            on_success=on_success,
            on_error=on_error,
        )

        self._pending_api_requests[image_name] = request_id
        logger.debug("[SceneSegment] Queued upload for '%s'", image_name)
        return True

    def _notify_upload_callback(self, image_name: str, success: bool, message: str):
        """Notify and clear the upload callback for an image."""
        callback = None
        with self._jobs_lock:
            state = self._jobs.get(image_name)
            if state:
                callback = state.upload_callback
                state.upload_callback = None

        # Call callback outside lock
        if callback:
            try:
                callback(success, message)
            except Exception as e:
                logger.error("[SceneSegment] Upload callback error: %s", e)

    # ========================================================================
    # EXPIRY DETECTION
    # ========================================================================

    def _is_expiry_error(self, error_msg: str) -> bool:
        """Check if an error indicates a job expiry."""
        if not error_msg:
            return False
        lower = error_msg.lower()
        if "expired" in lower or "job_not_active" in lower:
            return True
        # Match status code 410 as a standalone token (avoid false positives like "4100")
        return bool(re.search(r'\b410\b', error_msg))

    def _handle_expired_job(self, image_name: str):
        """Reset an expired job so the next operation re-uploads."""
        old_job_id = None
        with self._jobs_lock:
            state = self._jobs.get(image_name)
            if state:
                state.status = JobStatus.PENDING
                old_job_id = state.job_id
                state.job_id = None
                state.expires_at = None
        if old_job_id:
            # Server already expired this job; DELETE may return 404/410, ignore errors
            try:
                service = get_scene_segment_service()
                service.delete_job_async(old_job_id)
            except Exception:
                pass
        logger.debug("[SceneSegment] Job expired for '%s', cleared for re-upload", image_name)

    def _fail_pending_requests(self, state: JobState, error: str):
        """Fail all pending requests on a job (e.g., after expiry)."""
        with self._jobs_lock:
            for req in state.requests.values():
                if req.status in (RequestStatus.QUEUED, RequestStatus.GENERATING):
                    req.status = RequestStatus.FAILED
                    req.error = error
                    if req.callback:
                        try:
                            req.callback(False, None, error)
                        except Exception:
                            pass

    # ========================================================================
    # SEGMENTATION
    # ========================================================================

    def request_segmentation(
        self,
        image: bpy.types.Image,
        points: List[Dict[str, Any]],
        on_complete: Optional[Callable[[bool, Optional[bytes], str], None]] = None,
    ) -> bool:
        """
        Request point segmentation for an uploaded image.

        Args:
            image: Blender image (must be uploaded)
            points: List of point dicts with x, y (0-1), label (1 or 0)
            on_complete: Callback(success: bool, mask_bytes: Optional[bytes], message: str)

        Returns:
            True if request was queued, False if image not ready
        """
        if image is None:
            if on_complete:
                on_complete(False, None, "No image provided")
            return False

        with self._jobs_lock:
            state = self._jobs.get(image.name)
            if not state or state.status != JobStatus.READY:
                if on_complete:
                    on_complete(False, None, "Image not uploaded")
                return False
            job_id = state.job_id

        service = get_scene_segment_service()

        def on_success(response: APIResponse):
            # Extract data from nested response structure
            data = response.data or {}
            inner_data = data.get("data", data)
            request_id = inner_data.get("request_id")

            if not request_id:
                if on_complete:
                    on_complete(False, None, "No request_id in response")
                return

            # Create request tracker
            request = SegmentRequest(
                request_id=request_id,
                status=RequestStatus.QUEUED,
                callback=on_complete,
            )

            with self._jobs_lock:
                state.requests[request_id] = request

            # Start polling if not already running
            self._start_polling()

            logger.debug("[SceneSegment] Segmentation queued: request_id=%s", request_id)

        def on_error(error: Exception):
            error_msg = str(error)
            if self._is_expiry_error(error_msg):
                self._handle_expired_job(image.name)
                error_msg = "expired"
            if on_complete:
                on_complete(False, None, error_msg)
            logger.error("[SceneSegment] Segmentation request failed: %s", error)

        service.segment_point_async(
            job_id=job_id,
            points=points,
            on_success=on_success,
            on_error=on_error,
        )

        return True

    def request_box_segmentation(
        self,
        image: bpy.types.Image,
        box: Dict[str, float],
        on_complete: Optional[Callable[[bool, Optional[bytes], str], None]] = None,
    ) -> bool:
        """
        Request box segmentation for an uploaded image.

        Args:
            image: Blender image (must be uploaded)
            box: Box dict with x_min, y_min, x_max, y_max (0-1 normalized)
            on_complete: Callback(success: bool, mask_bytes: Optional[bytes], message: str)

        Returns:
            True if request was queued, False if image not ready
        """
        if image is None:
            if on_complete:
                on_complete(False, None, "No image provided")
            return False

        with self._jobs_lock:
            state = self._jobs.get(image.name)
            if not state or state.status != JobStatus.READY:
                if on_complete:
                    on_complete(False, None, "Image not uploaded")
                return False
            job_id = state.job_id

        service = get_scene_segment_service()

        def on_success(response: APIResponse):
            data = response.data or {}
            inner_data = data.get("data", data)
            request_id = inner_data.get("request_id")

            if not request_id:
                if on_complete:
                    on_complete(False, None, "No request_id in response")
                return

            request = SegmentRequest(
                request_id=request_id,
                status=RequestStatus.QUEUED,
                callback=on_complete,
            )

            with self._jobs_lock:
                state.requests[request_id] = request

            self._start_polling()
            logger.debug("[SceneSegment] Box segmentation queued: request_id=%s", request_id)

        def on_error(error: Exception):
            error_msg = str(error)
            if self._is_expiry_error(error_msg):
                self._handle_expired_job(image.name)
                error_msg = "expired"
            if on_complete:
                on_complete(False, None, error_msg)
            logger.error("[SceneSegment] Box segmentation request failed: %s", error)

        service.segment_box_async(
            job_id=job_id,
            box=box,
            on_success=on_success,
            on_error=on_error,
        )

        return True

    def request_mask_segmentation(
        self,
        image: bpy.types.Image,
        mask_bytes: bytes,
        on_complete: Optional[Callable[[bool, Optional[bytes], str], None]] = None,
    ) -> bool:
        """
        Request mask-based segmentation for an uploaded image (lasso refinement).

        Args:
            image: Blender image (must be uploaded)
            mask_bytes: Binary mask PNG (white=selected, black=background)
            on_complete: Callback(success: bool, mask_bytes: Optional[bytes], message: str)

        Returns:
            True if request was queued, False if image not ready
        """
        if image is None:
            if on_complete:
                on_complete(False, None, "No image provided")
            return False

        with self._jobs_lock:
            state = self._jobs.get(image.name)
            if not state or state.status != JobStatus.READY:
                if on_complete:
                    on_complete(False, None, "Image not uploaded")
                return False
            job_id = state.job_id

        service = get_scene_segment_service()

        def on_success(response: APIResponse):
            data = response.data or {}
            inner_data = data.get("data", data)
            request_id = inner_data.get("request_id")

            if not request_id:
                if on_complete:
                    on_complete(False, None, "No request_id in response")
                return

            request = SegmentRequest(
                request_id=request_id,
                status=RequestStatus.QUEUED,
                callback=on_complete,
            )

            with self._jobs_lock:
                state.requests[request_id] = request

            self._start_polling()
            logger.debug("[SceneSegment] Mask segmentation queued: request_id=%s", request_id)

        def on_error(error: Exception):
            error_msg = str(error)
            if self._is_expiry_error(error_msg):
                self._handle_expired_job(image.name)
                error_msg = "expired"
            if on_complete:
                on_complete(False, None, error_msg)
            logger.error("[SceneSegment] Mask segmentation request failed: %s", error)

        service.segment_mask_async(
            job_id=job_id,
            mask_bytes=mask_bytes,
            on_success=on_success,
            on_error=on_error,
        )

        return True

    # ========================================================================
    # POLLING
    # ========================================================================

    def _start_polling(self):
        """Start the polling timer if not already running."""
        if self._poll_timer_running:
            return

        self._poll_timer_running = True
        bpy.app.timers.register(self._poll_tick, first_interval=self._poll_interval)
        logger.debug("[SceneSegment] Started polling timer")

    def _poll_tick(self) -> Optional[float]:
        """
        Timer callback to poll all pending requests.
        Returns poll_interval to continue, None to stop.
        """
        # Collect all jobs with pending requests (snapshot under lock)
        pending_jobs: List[tuple] = []
        with self._jobs_lock:
            for image_name, state in list(self._jobs.items()):
                if state.status != JobStatus.READY or not state.job_id:
                    continue

                with self._jobs_lock:
                    pending_requests = [
                        req for req in state.requests.values()
                        if req.status in (RequestStatus.QUEUED, RequestStatus.GENERATING)
                    ]

                if pending_requests:
                    pending_jobs.append((image_name, state))

        # No pending requests - stop polling
        if not pending_jobs:
            self._poll_timer_running = False
            logger.debug("[SceneSegment] Stopped polling timer - no pending requests")
            return None

        # Poll each job in background (outside lock)
        for image_name, state in pending_jobs:
            self._poll_job(image_name, state)

        return self._poll_interval

    def _poll_job(self, image_name: str, state: JobState):
        """Poll a single job for request status updates."""
        service = get_scene_segment_service()

        def poll_in_background():
            try:
                response = service.get_job_status(state.job_id)
                data = response.data or {}
                inner_data = data.get("data", data)
                job_status = inner_data.get("status", "")
                requests_data = inner_data.get("requests", [])

                def process_on_main_thread():
                    if job_status == "expired":
                        self._handle_expired_job(image_name)
                        self._fail_pending_requests(state, "expired")
                        return None
                    self._process_poll_response(state, requests_data)
                    return None

                bpy.app.timers.register(process_on_main_thread, first_interval=0.0)

            except Exception as e:
                error_msg = str(e)
                if self._is_expiry_error(error_msg):
                    def handle_expired_on_main():
                        self._handle_expired_job(image_name)
                        self._fail_pending_requests(state, "expired")
                        return None
                    bpy.app.timers.register(handle_expired_on_main, first_interval=0.0)
                else:
                    logger.error("[SceneSegment] Poll error for %s: %s", image_name, e)

        thread = threading.Thread(target=poll_in_background, daemon=True)
        thread.start()

    def _process_poll_response(self, state: JobState, requests_data: List[Dict]):
        """Process poll response and update request statuses."""
        downloads_to_trigger = []
        callbacks_to_call = []

        for req_data in requests_data:
            request_id = req_data.get("request_id")
            status = req_data.get("status")

            with self._jobs_lock:
                if request_id not in state.requests:
                    continue

                request = state.requests[request_id]

                if status == "completed" and request.status not in (
                    RequestStatus.COMPLETED, RequestStatus.DOWNLOADING, RequestStatus.DOWNLOADED
                ):
                    request.status = RequestStatus.COMPLETED
                    downloads_to_trigger.append((state, request))

                elif status == "failed" and request.status != RequestStatus.FAILED:
                    request.status = RequestStatus.FAILED
                    request.error = req_data.get("error", "Unknown error")
                    if request.callback:
                        callbacks_to_call.append((request.callback, False, None, request.error))
                    request.callback = None
                    request.mask_bytes = None
                    state.requests.pop(request_id, None)

                elif status == "generating":
                    request.status = RequestStatus.GENERATING

        # Trigger downloads and callbacks outside lock
        for state, request in downloads_to_trigger:
            self._download_mask(state, request)

        for callback, success, data, msg in callbacks_to_call:
            try:
                callback(success, data, msg)
            except Exception as e:
                logger.error("[SceneSegment] Callback error: %s", e)

    # ========================================================================
    # MASK DOWNLOAD
    # ========================================================================

    def _download_mask(self, state: JobState, request: SegmentRequest):
        """Download mask for a completed request."""
        # Set DOWNLOADING status BEFORE starting thread (atomic, prevents duplicates)
        with self._jobs_lock:
            if request.status == RequestStatus.DOWNLOADING:
                return  # Already downloading, prevent duplicate
            request.status = RequestStatus.DOWNLOADING

        service = get_scene_segment_service()

        def download_in_background():
            try:
                response = service.download_mask(state.job_id, request.request_id)
                mask_bytes = response.raw.content if response.raw else None

                def complete_on_main_thread():
                    callback = None
                    callback_args = None

                    with self._jobs_lock:
                        if mask_bytes:
                            request.status = RequestStatus.DOWNLOADED
                            if request.callback:
                                callback = request.callback
                                callback_args = (True, mask_bytes, "Success")
                            logger.debug("[SceneSegment] Downloaded mask: %s bytes", len(mask_bytes))
                        else:
                            request.status = RequestStatus.FAILED
                            request.error = "Empty mask response"
                            if request.callback:
                                callback = request.callback
                                callback_args = (False, None, request.error)
                        request.mask_bytes = None
                        request.callback = None
                        state.requests.pop(request.request_id, None)

                    # Call callback outside lock
                    if callback:
                        try:
                            callback(*callback_args)
                        except Exception as e:
                            logger.error("[SceneSegment] Callback error: %s", e)
                    return None

                bpy.app.timers.register(complete_on_main_thread, first_interval=0.0)

            except Exception as e:
                def error_on_main_thread():
                    callback = None
                    error_msg = str(e)

                    with self._jobs_lock:
                        request.status = RequestStatus.FAILED
                        request.error = error_msg
                        if request.callback:
                            callback = request.callback
                        request.mask_bytes = None
                        request.callback = None
                        state.requests.pop(request.request_id, None)

                    # Call callback outside lock
                    if callback:
                        try:
                            callback(False, None, error_msg)
                        except Exception as cb_e:
                            logger.error("[SceneSegment] Callback error: %s", cb_e)
                    return None

                bpy.app.timers.register(error_on_main_thread, first_interval=0.0)

        thread = threading.Thread(target=download_in_background, daemon=True)
        thread.start()

    # ========================================================================
    # CLEANUP
    # ========================================================================

    def reset_image(self, image: bpy.types.Image):
        """Reset all state for an image (e.g., after image modified)."""
        if image is None:
            return

        with self._jobs_lock:
            state = self._jobs.pop(image.name, None)

        if state and state.job_id:
            # Delete job on server in background
            service = get_scene_segment_service()
            service.delete_job_async(state.job_id)

    def clear_all(self):
        """Clear all tracking data."""
        with self._jobs_lock:
            self._jobs.clear()
            self._pending_api_requests.clear()
        if self._poll_timer_running:
            self._poll_timer_running = False


# Singleton instance
_scene_segment_manager: Optional[SceneSegmentManager] = None


def get_scene_segment_manager() -> SceneSegmentManager:
    """Get or create the global Scene Segment manager instance."""
    global _scene_segment_manager
    if _scene_segment_manager is None:
        _scene_segment_manager = SceneSegmentManager()
    return _scene_segment_manager
