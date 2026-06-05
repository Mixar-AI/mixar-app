# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Plugin metrics → backend → Loki shipper (#25).

The plugin side of the metrics pipeline decided 2026-05-27. Local
metrics collected by ``performance_metrics.PerformanceMetrics`` are
batched and POSTed to ``/api/v1/agent/plugin-metrics`` on the backend,
which forwards each item to Loki tagged with the label set:

    session_id, instance_id, plugin_version, blender_version, metric_name

Design choices:

- Posting is fire-and-forget on a daemon thread so it never blocks
  the Blender main thread. If the backend is unreachable or the
  request fails we log a warning and drop the batch — metrics are
  not critical state.
- Batches are size-bounded (max 100 items per ``PluginMetricsBatch``)
  and time-bounded (call ``flush_metrics`` from a periodic timer in
  the host module).
- Authentication uses the same ``get_access_token`` helper the
  WebSocket and SSE channels share. Stale tokens here mean a single
  dropped batch — the next flush will mint a fresh token via the
  shared refresh path.
"""

import threading
from typing import Callable, Dict, List, Optional

import requests

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


_DEFAULT_TIMEOUT = 5.0
_PLUGIN_METRICS_PATH = "/api/v1/agent/plugin-metrics"
_MAX_BATCH_SIZE = 100  # mirrors the backend schema's metrics list cap


def _url(host: str) -> str:
    """Concatenate host + endpoint. Host may have a trailing slash."""
    return f"{host.rstrip('/')}{_PLUGIN_METRICS_PATH}"


def post_metrics_batch(
    host: str,
    token: str,
    instance_id: str,
    session_id: str,
    plugin_version: str,
    blender_version: str,
    metrics: List[Dict],
) -> bool:
    """POST a batch of metrics to the backend.

    Returns ``True`` on a 2xx response. On any failure (network,
    timeout, non-2xx), logs a warning and returns ``False``. Never
    raises — observability flakiness must not crash the plugin.

    The batch is split client-side if it exceeds the backend's
    100-item cap: each chunk POSTs independently so a partial
    failure doesn't lose every metric in the batch.
    """
    if not metrics:
        return True
    if not host or not token:
        # The plugin can call this before auth completes; soft-fail.
        return False

    payload_template = {
        "instance_id": instance_id,
        "session_id": session_id,
        "plugin_version": plugin_version,
        "blender_version": blender_version,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    success = True
    # Split into chunks of <= _MAX_BATCH_SIZE so the backend's
    # min_length=1, max_length=100 validator never rejects us.
    for i in range(0, len(metrics), _MAX_BATCH_SIZE):
        chunk = metrics[i : i + _MAX_BATCH_SIZE]
        body = {**payload_template, "metrics": chunk}
        try:
            resp = requests.post(
                _url(host), headers=headers, json=body,
                timeout=_DEFAULT_TIMEOUT,
            )
            if not resp.ok:
                logger.warning(
                    f"plugin-metrics POST returned {resp.status_code}: "
                    f"{resp.text[:200]}"
                )
                success = False
        except Exception as e:
            logger.warning(f"plugin-metrics POST error: {type(e).__name__}: {e}")
            success = False
    return success


def post_metrics_batch_async(
    host: str,
    token: str,
    instance_id: str,
    session_id: str,
    plugin_version: str,
    blender_version: str,
    metrics: List[Dict],
) -> None:
    """Fire-and-forget wrapper around ``post_metrics_batch``.

    Runs on a short-lived daemon thread so it never blocks the
    Blender main thread. The thread terminates after the POST
    completes; there's no shared state to clean up.
    """
    if not metrics:
        return

    # Snapshot the metrics list so callers can mutate theirs while
    # the thread runs.
    metrics_copy = list(metrics)

    def _worker():
        try:
            post_metrics_batch(
                host=host, token=token,
                instance_id=instance_id, session_id=session_id,
                plugin_version=plugin_version,
                blender_version=blender_version,
                metrics=metrics_copy,
            )
        except Exception as e:
            # Should be unreachable — post_metrics_batch catches its
            # own exceptions. Belt-and-braces in case of a regression.
            logger.warning(
                f"plugin-metrics async worker crashed: {type(e).__name__}: {e}"
            )

    threading.Thread(
        target=_worker,
        daemon=True,
        name="MixarMetricsLokiPoster",
    ).start()
