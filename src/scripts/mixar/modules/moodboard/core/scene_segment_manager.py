# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded, main-thread-safe Scene Segment (SAM3) coordination."""

import threading
from typing import Dict, Optional

import bpy

from ...common.api.services.scene_segment_service import get_scene_segment_service
from ..constants import SCENE_SEGMENT_POLL_INTERVAL_SECONDS
from .scene_segment_poll_guard import SceneSegmentPollGuard
from .scene_segment_requests import SceneSegmentRequestMixin
from .scene_segment_types import JobState, JobStatus
from .scene_segment_upload import SceneSegmentUploadMixin


class SceneSegmentManager(SceneSegmentUploadMixin, SceneSegmentRequestMixin):
    """Coordinate uploads and segmentation without touching Blender in workers.

    The shared HTTP client delivers callbacks on Blender's main thread. A
    per-image lease prevents overlapping status calls, while the request mixin
    applies an end-to-end deadline so a stalled GPU worker cannot leave a
    moodboard tool pending forever.
    """

    def __init__(self):
        self._jobs: Dict[str, JobState] = {}
        self._pending_api_requests: Dict[str, str] = {}
        self._poll_timer_running = False
        self._poll_interval = SCENE_SEGMENT_POLL_INTERVAL_SECONDS
        self._jobs_lock = threading.RLock()
        self._poll_guard = SceneSegmentPollGuard()

    def get_job_state(self, image: bpy.types.Image) -> Optional[JobState]:
        """Return the tracked state for *image*."""
        if image is None:
            return None
        with self._jobs_lock:
            return self._jobs.get(image.name)

    def is_ready(self, image: bpy.types.Image) -> bool:
        """Whether *image* has an active server upload."""
        state = self.get_job_state(image)
        return state is not None and state.status == JobStatus.READY

    def is_uploading(self, image: bpy.types.Image) -> bool:
        """Whether *image* is currently uploading."""
        state = self.get_job_state(image)
        return state is not None and state.status == JobStatus.UPLOADING

    def get_job_id(self, image: bpy.types.Image) -> Optional[str]:
        """Return the active server job identifier for *image*."""
        state = self.get_job_state(image)
        return state.job_id if state else None

    def get_uploaded_image_size(self, image: bpy.types.Image):
        """Return ``(width, height)`` reported by the upload endpoint."""
        state = self.get_job_state(image)
        size = state.image_size if state else None
        if not isinstance(size, dict):
            return None
        width = size.get("width")
        height = size.get("height")
        if not width or not height:
            return None
        return int(width), int(height)

    def reset_image(self, image: bpy.types.Image):
        """Forget one image and asynchronously release its server job."""
        if image is None:
            return
        with self._jobs_lock:
            state = self._jobs.pop(image.name, None)
            self._pending_api_requests.pop(image.name, None)
        self._poll_guard.clear(image.name)
        if state and state.job_id:
            try:
                get_scene_segment_service().delete_job_async(state.job_id)
            except Exception:
                pass

    def clear_all(self):
        """Clear local tracking during module teardown."""
        with self._jobs_lock:
            self._jobs.clear()
            self._pending_api_requests.clear()
        self._poll_guard.clear()
        self._poll_timer_running = False


_scene_segment_manager: Optional[SceneSegmentManager] = None


def get_scene_segment_manager() -> SceneSegmentManager:
    """Return the process-wide moodboard segmentation manager."""
    global _scene_segment_manager
    if _scene_segment_manager is None:
        _scene_segment_manager = SceneSegmentManager()
    return _scene_segment_manager
