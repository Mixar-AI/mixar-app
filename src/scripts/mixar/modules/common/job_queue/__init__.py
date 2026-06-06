# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reusable feature-agnostic generation job queue.

Public surface:
    from mixar.modules.common.job_queue import (
        Job, JobState, get_queue, TERMINAL_STATES, RUNNING_STATES,
    )
"""

from .core.job import Job, JobState, TERMINAL_STATES, RUNNING_STATES
from .core.queue_manager import get_queue, FeatureQueue

__all__ = (
    "Job",
    "JobState",
    "TERMINAL_STATES",
    "RUNNING_STATES",
    "get_queue",
    "FeatureQueue",
)
