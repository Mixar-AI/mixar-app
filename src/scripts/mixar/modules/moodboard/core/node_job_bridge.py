# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mirror unified queue jobs onto their persistent moodboard action nodes."""

import bpy

from mixar.modules.common.job_queue.core.job import JobState, RUNNING_STATES
from .node_graph import action_node_by_id


_STATE_MAP = {
    JobState.PENDING: 'QUEUED',
    JobState.PAUSED_AUTH: 'QUEUED',
    JobState.SUCCESS: 'SUCCESS',
    JobState.FAILED: 'FAILED',
    JobState.CANCELLED: 'CANCELLED',
}

# Redraw pump for the running-node glow (C++ draw_running_glow). 15 fps is
# visually smooth for its slow ~2.9s alpha breathe, and a generation runs for
# minutes — pumping the full canvas repaint at 30 fps doubled the draw cost of
# every generating session for no visible gain. Job-state changes alone only
# repaint on discrete edges, hence the timer.
_PULSE_INTERVAL_S = 1.0 / 15.0


def _redraw_mixie_areas() -> None:
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()
    except Exception:
        pass


def _any_node_generating() -> bool:
    for scene in bpy.data.scenes:
        for node in getattr(scene, "mixie_moodboard_action_nodes", ()):
            if node.state in {'QUEUED', 'RUNNING'}:
                return True
    return False


def _pulse_tick():
    """Repaint the moodboard while any node generates; self-stop when none do."""
    if not _any_node_generating():
        return None
    _redraw_mixie_areas()
    return _PULSE_INTERVAL_S


def ensure_pulse_timer() -> None:
    """Start the glow redraw pump if a node is generating and it isn't already
    running. ``_pulse_tick`` unregisters itself once nothing is generating."""
    try:
        if bpy.app.timers.is_registered(_pulse_tick):
            return
        if _any_node_generating():
            bpy.app.timers.register(_pulse_tick)
    except Exception:
        pass


def sync_graph_jobs(queue) -> None:
    changed = False
    for job in queue.snapshot():
        node_id = str(getattr(job, "graph_node_id", "") or "")
        if not node_id:
            continue
        scene = bpy.data.scenes.get(getattr(job, "scene_name", ""))
        if scene is None:
            continue
        node = action_node_by_id(scene, node_id)
        if node is None:
            continue
        state = 'RUNNING' if job.state in RUNNING_STATES else _STATE_MAP.get(job.state)
        if state and node.state != state:
            node.state = state
            changed = True
        job_id = str(getattr(job, "backend_job_id", "") or job.id)
        if node.job_id != job_id:
            node.job_id = job_id
            changed = True
        error = str(getattr(job, "user_message", "") or getattr(job, "error", "") or "")
        if node.error != error:
            node.error = error
            changed = True

    if changed:
        _redraw_mixie_areas()
    # A node that just entered QUEUED/RUNNING needs the continuous pump so its
    # glow animates; self-gates and no-ops when nothing is generating.
    ensure_pulse_timer()


def ensure_graph_listener(feature_key: str) -> None:
    from mixar.modules.common.job_queue.core.queue_manager import get_queue

    get_queue(feature_key).add_listener(sync_graph_jobs)


def find_active_node_job(node_id: str):
    """The live queue (queue, job) pair driving *node_id*, or (None, None).

    Looked up by ``graph_node_id`` across every feature queue rather than by
    the node's ``job_id`` — the node's stored id flips from the local queue id
    to the backend id once the submit lands, so it cannot address the queue.
    """
    if not node_id:
        return None, None
    from mixar.modules.common.job_queue.core.queue_manager import (
        ACTIVE_JOB_STATES,
        all_queues,
    )

    for queue in all_queues():
        for job in queue.snapshot():
            if (
                str(getattr(job, "graph_node_id", "") or "") == node_id
                and job.state in ACTIVE_JOB_STATES
            ):
                return queue, job
    return None, None


def cancel_node_job(node_id: str) -> bool:
    """Cancel the queue job a node is waiting on. True when one was cancelled.

    The queue's cancel path notifies listeners, so ``sync_graph_jobs`` mirrors
    the CANCELLED state back onto the node without extra wiring.
    """
    try:
        queue, job = find_active_node_job(node_id)
    except Exception:
        return False
    if queue is None or job is None:
        return False
    queue.cancel(job.id)
    return True
