# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Warm the layered-material map cache before the apply script arrives.

The backend runs one script per connection at a time, and the executor holds
an apply script at the head of its queue until that script's maps are on disk,
so a slow download used to stall every other agent's scripts and captures
behind it. The backend now calls this first: the call starts background
downloads and returns at once, later calls only report progress, and the apply
is sent once every map is cached, so it holds the connection for the build
alone (well under a second in measured runs).
"""

from __future__ import annotations

from mixar.modules.paint.layered_build.download import prefetch_status, start_prefetch

MAX_URLS = 32


def prefetch_layered_maps(urls=None, start: bool = True) -> dict:
    """Start (``start=True``) and/or report background downloads of map URLs.

    Returns ``{"success", "total", "ready", "pending", "missing", "failed",
    "started", "complete"}``; ``complete`` is true once every URL is on disk.
    Never blocks on the network.
    """
    wanted = [str(u) for u in (urls or []) if u][:MAX_URLS]
    started = start_prefetch(wanted) if start else 0
    status = prefetch_status(wanted)
    status.update({
        "success": True,
        "started": started,
        "complete": status["total"] > 0 and status["ready"] == status["total"],
    })
    return status
