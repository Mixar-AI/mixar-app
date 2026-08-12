# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Upload and expiry behavior for :mod:`scene_segment_manager`."""

import re
import time
from datetime import datetime
from typing import Callable, Optional

from mixar.config.logging_config import get_logger
from ...common.api.response import APIResponse
from ...common.api.services.scene_segment_service import get_scene_segment_service
from .scene_segment_image import compress_image_for_scene_segment
from .scene_segment_types import (
    JobState,
    JobStatus,
    drain_upload_callbacks,
)

logger = get_logger(__name__)


class SceneSegmentUploadMixin:
    """Manage one shared upload per image and notify every waiting tool."""

    def queue_upload(
        self,
        image,
        img_item=None,
        on_complete: Optional[Callable[[bool, str], None]] = None,
    ) -> bool:
        """Upload *image*, or join the callback list of its active upload."""
        if image is None:
            if on_complete:
                on_complete(False, "No image provided")
            return False

        image_name = image.name
        immediate_callback = None
        already_ready = False
        with self._jobs_lock:
            state = self._jobs.get(image_name)
            if state and state.status == JobStatus.READY:
                if state.expires_at and time.time() > state.expires_at - 300:
                    state.status = JobStatus.PENDING
                    state.job_id = None
                    state.expires_at = None
                else:
                    already_ready = True
                    immediate_callback = on_complete

            if already_ready:
                pass
            elif state and state.status == JobStatus.UPLOADING:
                if on_complete:
                    state.upload_callbacks.append(on_complete)
                return False
            else:
                state = JobState(status=JobStatus.UPLOADING)
                if on_complete:
                    state.upload_callbacks.append(on_complete)
                self._jobs[image_name] = state

        if already_ready:
            if immediate_callback:
                immediate_callback(True, "Already uploaded")
            return False

        try:
            image_bytes = compress_image_for_scene_segment(image, img_item)
        except Exception as exc:
            self._finish_upload(
                image_name, state, False, f"Compression failed: {exc}",
            )
            return False

        def on_success(response: APIResponse):
            data = response.data or {}
            inner_data = data.get("data", data)
            job_id = inner_data.get("job_id")
            if not job_id:
                self._finish_upload(image_name, state, False, "No job_id in response")
                return

            with self._jobs_lock:
                if self._jobs.get(image_name) is not state:
                    return
                # Ignore a real response arriving after this async callback's
                # timeout already failed the upload.
                if state.status != JobStatus.UPLOADING:
                    return
                state.job_id = job_id
                state.status = JobStatus.READY
                state.image_size = inner_data.get("image_size")
                expires_at = inner_data.get("expires_at")
                if expires_at:
                    try:
                        state.expires_at = datetime.fromisoformat(
                            expires_at.replace("Z", "+00:00")
                        ).timestamp()
                    except (ValueError, AttributeError):
                        state.expires_at = None
                self._pending_api_requests.pop(image_name, None)

            self._notify_upload_callbacks(state, True, "Upload successful")
            logger.debug("[SceneSegment] Uploaded '%s'", image_name)

        def on_error(error: Exception):
            self._finish_upload(image_name, state, False, str(error))
            logger.error("[SceneSegment] Upload failed for '%s': %s", image_name, error)

        try:
            request_id = get_scene_segment_service().upload_image_async(
                image_bytes=image_bytes,
                filename=f"{image_name}.jpg",
                on_success=on_success,
                on_error=on_error,
            )
        except Exception as exc:
            self._finish_upload(image_name, state, False, str(exc))
            return False

        with self._jobs_lock:
            if self._jobs.get(image_name) is state:
                self._pending_api_requests[image_name] = request_id
        logger.debug("[SceneSegment] Queued upload for '%s'", image_name)
        return True

    def _finish_upload(self, image_name, state, success: bool, message: str):
        with self._jobs_lock:
            if self._jobs.get(image_name) is not state:
                return
            state.status = JobStatus.READY if success else JobStatus.FAILED
            self._pending_api_requests.pop(image_name, None)
        self._notify_upload_callbacks(state, success, message)

    def _notify_upload_callbacks(self, state, success: bool, message: str):
        with self._jobs_lock:
            callbacks = drain_upload_callbacks(state)
        for callback in callbacks:
            try:
                callback(success, message)
            except Exception as exc:
                logger.error("[SceneSegment] Upload callback error: %s", exc)

    @staticmethod
    def _is_expiry_error(error_msg: str) -> bool:
        if not error_msg:
            return False
        lower = error_msg.lower()
        if "expired" in lower or "job_not_active" in lower:
            return True
        return bool(re.search(r'\b410\b', error_msg))

    def _handle_expired_job(self, image_name: str):
        old_job_id = None
        with self._jobs_lock:
            state = self._jobs.get(image_name)
            if state:
                state.status = JobStatus.PENDING
                old_job_id = state.job_id
                state.job_id = None
                state.expires_at = None
        if old_job_id:
            try:
                get_scene_segment_service().delete_job_async(old_job_id)
            except Exception:
                pass
        logger.debug("[SceneSegment] Job expired for '%s'", image_name)
