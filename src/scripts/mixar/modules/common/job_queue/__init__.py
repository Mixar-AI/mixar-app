# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reusable feature-agnostic generation job queue.

Public surface:
    from mixar.modules.common.job_queue import (
        Job, JobState, get_queue, TERMINAL_STATES, RUNNING_STATES,
        # Helpers for concrete queue implementations
        get_queue_with_listener,
        create_scene_flag_listener,
        show_batch_summary_popup,
        download_images_to_moodboard,
        extract_image_urls,
    )
"""

from .core.job import Job, JobState, TERMINAL_STATES, RUNNING_STATES
from .core.queue_manager import get_queue, FeatureQueue
from .core.generic_jobs import AsyncGLBJob, StreamingVideoJob, SyncImageJob
from .core.enqueue import enqueue_generation
from .core.helpers import (
    create_scene_flag_listener,
    download_images_to_moodboard,
    extract_image_urls,
    get_queue_with_listener,
    show_batch_summary_popup,
)

__all__ = (
    "Job",
    "JobState",
    "TERMINAL_STATES",
    "RUNNING_STATES",
    "get_queue",
    "FeatureQueue",
    # Generic jobs
    "AsyncGLBJob",
    "SyncImageJob",
    "StreamingVideoJob",
    "enqueue_generation",
    # Helpers
    "create_scene_flag_listener",
    "download_images_to_moodboard",
    "extract_image_urls",
    "get_queue_with_listener",
    "show_batch_summary_popup",
)
