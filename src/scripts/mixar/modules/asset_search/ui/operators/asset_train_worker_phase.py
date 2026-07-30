# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""RENDER_WORKER phase handler for the training modal.

Split from asset_train_ops (file-size limit): drives the headless
preview-render worker — polls its results.jsonl for per-asset progress,
handles cancel/stall, collects the produced JPEGs on completion, and falls
back to the in-process session if the worker dies before producing anything.
"""

import json
import os

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.core import preview_worker
from mixar.modules.asset_search.core.train_support import set_failures

logger = get_logger(__name__)


def _items_from_plan(worker):
    """Re-read the worker's plan for the in-process fallback path."""
    try:
        with open(os.path.join(worker.work_dir, "plan.json"),
                  encoding="utf-8") as fh:
            return json.load(fh).get("items", [])
    except OSError:
        return []


def handle_render_worker(op, context, state):
    """One modal tick of the RENDER_WORKER phase. Returns the modal result."""
    worker = op._worker
    new, done, stalled = preview_worker.poll(worker)

    if new:
        last = new[-1]
        op._update_render_progress(
            state, len(worker.results), worker.total, last.get("label", ""))
        set_failures(state, op._worker_failures + worker.failures)
        state.phase_text = (
            f"Rendering previews in background "
            f"{len(worker.results)}/{worker.total}"
        )
        op._redraw(context)

    if state.cancel_requested and not done:
        preview_worker.stop(worker)
        collected = preview_worker.collect_images(worker)
        preview_worker.cleanup(worker)
        op._worker = None
        return op._cancel_render(context, state, collected)

    if stalled:
        logger.error("[Asset Training] Worker stalled — %s",
                     preview_worker.worker_exit_summary(worker))
        preview_worker.stop(worker)
        preview_worker.cleanup(worker)
        op._worker = None
        op._finish(context, success=False,
                   message="Background renderer stalled — try again")
        return {"CANCELLED"}

    if not done:
        return {"RUNNING_MODAL"}

    # Worker finished (or died). Died before ANY result -> in-process fallback.
    if not worker.results and worker.proc.poll() not in (0, None):
        logger.warning("[Asset Training] Worker died early (%s) — "
                       "falling back to in-process render",
                       preview_worker.worker_exit_summary(worker))
        items = _items_from_plan(worker)
        preview_worker.cleanup(worker)
        op._worker = None
        if items:
            return op._start_inprocess_session(context, state, items)
        op._finish(context, success=False,
                   message="Preview renderer failed to start")
        return {"CANCELLED"}

    collected = preview_worker.collect_images(worker)
    failures = op._worker_failures + worker.failures
    reused = sum(1 for r in worker.ok_results
                 if (r.get("info") or {}).get("reused_preview"))
    if reused:
        state.prepare_note = (
            (state.prepare_note + " · " if state.prepare_note else "")
            + f"{reused} thumbnails reused (not re-rendered)"
        )
    preview_worker.cleanup(worker)
    op._worker = None
    return op._renders_complete(context, state, collected, failures)
