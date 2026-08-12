# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Request, polling, and download behavior for Scene Segment."""

import time
from typing import Any, Callable, Dict, List, Optional

import bpy

from mixar.config.logging_config import get_logger
from ...common.api.response import APIResponse
from ...common.api.services.scene_segment_service import get_scene_segment_service
from ..constants import (
    SCENE_SEGMENT_HTTP_TIMEOUT_SECONDS,
    SCENE_SEGMENT_REQUEST_TIMEOUT_SECONDS,
)
from .scene_segment_types import (
    JobState,
    JobStatus,
    RequestStatus,
    SegmentCallback,
    SegmentRequest,
    expire_stalled_requests,
)

logger = get_logger(__name__)


class SceneSegmentRequestMixin:
    """Submit all prompt types through one bounded async lifecycle."""

    def request_segmentation(
        self, image, points: List[Dict[str, Any]],
        on_complete: Optional[SegmentCallback] = None,
    ) -> bool:
        return self._request(
            image, on_complete, "Point",
            lambda service, job_id, success, error: service.segment_point_async(
                job_id=job_id, points=points,
                on_success=success, on_error=error,
            ),
        )

    def request_box_segmentation(
        self, image, box: Dict[str, float],
        on_complete: Optional[SegmentCallback] = None,
    ) -> bool:
        return self._request(
            image, on_complete, "Box",
            lambda service, job_id, success, error: service.segment_box_async(
                job_id=job_id, box=box,
                on_success=success, on_error=error,
            ),
        )

    def request_mask_segmentation(
        self, image, mask_bytes: bytes,
        on_complete: Optional[SegmentCallback] = None,
    ) -> bool:
        return self._request(
            image, on_complete, "Mask",
            lambda service, job_id, success, error: service.segment_mask_async(
                job_id=job_id, mask_bytes=mask_bytes,
                on_success=success, on_error=error,
            ),
        )

    def _request(
        self,
        image,
        on_complete: Optional[SegmentCallback],
        label: str,
        submit: Callable,
    ) -> bool:
        if image is None:
            if on_complete:
                on_complete(False, None, "No image provided")
            return False

        image_name = image.name
        unavailable = False
        with self._jobs_lock:
            state = self._jobs.get(image_name)
            if not state or state.status != JobStatus.READY or not state.job_id:
                unavailable = True
                job_id = None
            else:
                job_id = state.job_id
        if unavailable:
            if on_complete:
                on_complete(False, None, "Image not uploaded")
            return False

        def on_success(response: APIResponse):
            data = response.data or {}
            inner_data = data.get("data", data)
            request_id = inner_data.get("request_id")
            if not request_id:
                if on_complete:
                    on_complete(False, None, "No request_id in response")
                return

            with self._jobs_lock:
                if (
                    self._jobs.get(image_name) is not state
                    or state.status != JobStatus.READY
                    or state.job_id != job_id
                ):
                    return
                state.requests[request_id] = SegmentRequest(
                    request_id=request_id,
                    callback=on_complete,
                )
            self._start_polling()
            logger.debug(
                "[SceneSegment] %s segmentation queued: request_id=%s",
                label, request_id,
            )

        def on_error(error: Exception):
            error_msg = str(error)
            if self._is_expiry_error(error_msg):
                self._handle_expired_job(image_name)
                error_msg = "expired"
            if on_complete:
                on_complete(False, None, error_msg)
            logger.error("[SceneSegment] %s request failed: %s", label, error)

        try:
            submit(get_scene_segment_service(), job_id, on_success, on_error)
        except Exception as exc:
            on_error(exc)
            return False
        return True

    def _start_polling(self):
        if self._poll_timer_running:
            return
        self._poll_timer_running = True
        try:
            bpy.app.timers.register(
                self._poll_tick, first_interval=self._poll_interval,
            )
        except Exception:
            self._poll_timer_running = False
            raise
        logger.debug("[SceneSegment] Started polling timer")

    def _poll_tick(self) -> Optional[float]:
        """Poll pending requests without ever creating raw worker threads."""
        try:
            callbacks = self._expire_stalled_requests(time.monotonic())
            for callback in callbacks:
                self._call_segment_callback(
                    callback, False, None,
                    "Segmentation timed out; please try again",
                )

            pending_jobs = []
            with self._jobs_lock:
                for image_name, state in list(self._jobs.items()):
                    if state.status != JobStatus.READY or not state.job_id:
                        continue
                    if any(
                        request.status in (
                            RequestStatus.QUEUED,
                            RequestStatus.GENERATING,
                        )
                        for request in state.requests.values()
                    ):
                        pending_jobs.append((image_name, state))

            if not pending_jobs:
                self._poll_timer_running = False
                logger.debug("[SceneSegment] Stopped polling timer")
                return None

            for image_name, state in pending_jobs:
                self._poll_job(image_name, state)
            return self._poll_interval
        except Exception as exc:
            # An uncaught timer exception silently unregisters Blender timers.
            # Keep it alive so active tools still reach their deadline.
            logger.error("[SceneSegment] Poll timer error: %s", exc, exc_info=True)
            return self._poll_interval

    def _expire_stalled_requests(self, now: float):
        with self._jobs_lock:
            return expire_stalled_requests(
                self._jobs.values(),
                now,
                SCENE_SEGMENT_REQUEST_TIMEOUT_SECONDS,
            )

    def _poll_job(self, image_name: str, state: JobState):
        lease = self._poll_guard.acquire(image_name)
        if lease is None:
            return
        with self._jobs_lock:
            job_id = state.job_id
        if not job_id:
            self._poll_guard.release(image_name, lease)
            return

        def on_success(response: APIResponse):
            try:
                with self._jobs_lock:
                    if (
                        self._jobs.get(image_name) is not state
                        or state.job_id != job_id
                    ):
                        return
                data = response.data or {}
                inner_data = data.get("data", data)
                if inner_data.get("status", "") == "expired":
                    self._handle_expired_job(image_name)
                    self._fail_requests(state, "expired")
                else:
                    self._process_poll_response(
                        state, inner_data.get("requests", []),
                    )
            finally:
                self._poll_guard.release(image_name, lease)

        def on_error(error: Exception):
            try:
                error_msg = str(error)
                if self._is_expiry_error(error_msg):
                    self._handle_expired_job(image_name)
                    self._fail_requests(state, "expired")
                else:
                    logger.error(
                        "[SceneSegment] Poll error for %s: %s",
                        image_name, error,
                    )
            finally:
                self._poll_guard.release(image_name, lease)

        try:
            get_scene_segment_service().get_job_status_async(
                job_id,
                on_success=on_success,
                on_error=on_error,
                timeout=SCENE_SEGMENT_HTTP_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            on_error(exc)

    def _process_poll_response(self, state: JobState, requests_data: List[Dict]):
        downloads = []
        failures = []
        with self._jobs_lock:
            for data in requests_data:
                request_id = data.get("request_id")
                request = state.requests.get(request_id)
                if not request:
                    continue
                status = data.get("status")
                if status == "completed" and request.status in (
                    RequestStatus.QUEUED, RequestStatus.GENERATING,
                ):
                    request.status = RequestStatus.COMPLETED
                    downloads.append(request)
                elif status == "failed":
                    failures.append((request, data.get("error", "Unknown error")))
                elif status == "generating":
                    request.status = RequestStatus.GENERATING

        for request in downloads:
            self._download_mask(state, request)
        for request, error in failures:
            self._finish_request(state, request, False, None, error)

    def _download_mask(self, state: JobState, request: SegmentRequest):
        with self._jobs_lock:
            if state.requests.get(request.request_id) is not request:
                return
            if request.status == RequestStatus.DOWNLOADING:
                return
            request.status = RequestStatus.DOWNLOADING
            job_id = state.job_id

        def on_success(response: APIResponse):
            mask_bytes = response.raw.content if response.raw else None
            if mask_bytes:
                logger.debug("[SceneSegment] Downloaded mask: %s bytes", len(mask_bytes))
                self._finish_request(
                    state, request, True, mask_bytes, "Success",
                )
            else:
                self._finish_request(
                    state, request, False, None, "Empty mask response",
                )

        def on_error(error: Exception):
            self._finish_request(state, request, False, None, str(error))

        try:
            get_scene_segment_service().download_mask_async(
                job_id,
                request.request_id,
                on_success=on_success,
                on_error=on_error,
                timeout=SCENE_SEGMENT_HTTP_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            on_error(exc)

    def _finish_request(
        self, state, request, success: bool,
        mask_bytes: Optional[bytes], message: str,
    ):
        callback = None
        with self._jobs_lock:
            if state.requests.get(request.request_id) is not request:
                return
            request.status = (
                RequestStatus.DOWNLOADED if success else RequestStatus.FAILED
            )
            request.error = None if success else message
            callback = request.callback
            request.callback = None
            state.requests.pop(request.request_id, None)
        self._call_segment_callback(callback, success, mask_bytes, message)

    def _fail_requests(self, state: JobState, error: str):
        callbacks = []
        with self._jobs_lock:
            for request_id, request in list(state.requests.items()):
                if request.callback:
                    callbacks.append(request.callback)
                request.status = RequestStatus.FAILED
                request.error = error
                request.callback = None
                state.requests.pop(request_id, None)
        for callback in callbacks:
            self._call_segment_callback(callback, False, None, error)

    @staticmethod
    def _call_segment_callback(callback, success, mask_bytes, message):
        if not callback:
            return
        try:
            callback(success, mask_bytes, message)
        except Exception as exc:
            logger.error("[SceneSegment] Callback error: %s", exc, exc_info=True)
