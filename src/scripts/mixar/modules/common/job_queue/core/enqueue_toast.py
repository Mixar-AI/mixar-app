# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transient viewport toast confirming a generation entered the queue.

Users routinely miss the agent's chat text saying a generation was queued,
so every ``FeatureQueue.submit()`` also raises a small auto-fading toast in
the viewport's top-right corner with a "View Queue" action.

Burst aggregation: agent scripts and multi-mesh fan-outs enqueue jobs one
at a time, sometimes seconds apart. The toast id is stable and the store's
``push()`` replaces an existing item with the same id AND restarts its TTL,
so while jobs keep arriving one toast stays on screen and its count climbs
("3 generations queued"). A burst ends once no job has been queued for a
full toast lifetime; the next enqueue then starts a fresh count. A manual
dismiss mid-burst is intentionally NOT a reset — the next job re-shows the
toast with the cumulative burst count, which is still the truthful number.
"""

import time

from ..constants import ENQUEUE_TOAST_ID, ENQUEUE_TOAST_TTL_MS

_burst_count = 0
_last_push = 0.0


def reset_burst() -> None:
    """Forget the current burst (tests / defensive re-init)."""
    global _burst_count, _last_push
    _burst_count = 0
    _last_push = 0.0


def notify_job_enqueued(job) -> None:
    """Show/refresh the aggregated "generation queued" toast for ``job``."""
    global _burst_count, _last_push
    now = time.monotonic()
    if _burst_count and (now - _last_push) * 1000.0 > ENQUEUE_TOAST_TTL_MS:
        _burst_count = 0  # previous toast already faded — start a new burst
    _burst_count += 1
    _last_push = now

    # display_label strips the agent-batch prefix + dedup hash the raw
    # label carries (same choice as the failure toast).
    label = getattr(job, "display_label", "") or getattr(job, "label", "")
    if _burst_count == 1:
        title = "Generation queued"
        body = label
    else:
        title = f"{_burst_count} generations queued"
        body = f"Latest: {label}" if label else ""

    from mixar.modules.common.notifications.store import (
        NotificationAction,
        get_notification_store,
    )

    get_notification_store().push(
        "info",
        title,
        body=body,
        ttl_ms=ENQUEUE_TOAST_TTL_MS,
        id=ENQUEUE_TOAST_ID,
        actions=[
            NotificationAction(
                label="View Queue",
                operator="mixie.queue_view",
                style="primary",
            ),
        ],
    )
