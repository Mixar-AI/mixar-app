# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unified generation-queue sidebar drawing."""

from mixar.modules.moodboard.constants import SEP_INTRA


def draw_queue(layout, context):
    """Draw the unified queue with filter chips and one flat job list."""
    try:
        from mixar.modules.common.job_queue.core.job import JobState
        from mixar.modules.common.job_queue.core.queue_manager import all_queues
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
            draw_unified_queue_panel,
        )
    except Exception:
        layout.label(text="Queue system not available", icon='INFO')
        return

    terminal_states = (JobState.SUCCESS, JobState.FAILED, JobState.CANCELLED)
    done_terminal = sum(
        1 for queue in all_queues() for job in queue.snapshot()
        if job.state in terminal_states
    )
    draw_unified_queue_panel(layout, context)

    if done_terminal:
        layout.separator(factor=SEP_INTRA)
        layout.operator(
            "mixie.queue_clear_all_completed",
            text="Clear All Completed", icon='TRASH',
        )
