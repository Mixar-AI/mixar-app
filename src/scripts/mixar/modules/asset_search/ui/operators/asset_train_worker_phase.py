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
from mixar.modules.asset_search.core.train_support import (
    launch_thumbnail_backfill,
    set_failures,
)

logger = get_logger(__name__)


def _items_from_plan(worker):
    """Re-read the combined plan for the in-process fallback path.

    The workers execute per-shard plans in their own subdirectories; the root
    plan.json is written purely so this fallback can recover the FULL item list.
    """
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
        # Convert THIS tick's results and hand them to the uploader, so the
        # network works while the remaining assets are still rendering.
        op._feed_collected(
            preview_worker.results_to_infos(new, op._used_names)
        )
        last = new[-1]
        op._update_render_progress(
            state, len(worker.results), worker.total, last.get("label", ""))
        set_failures(state, op._worker_failures + worker.failures)
        state.phase_text = (
            f"Rendering previews in background "
            f"{len(worker.results)}/{worker.total}" + op._upload_note()
        )
        op._redraw(context)

    if state.cancel_requested and not done:
        preview_worker.stop(worker)
        # The previews are FILES now — the work dir has to outlive this phase
        # (an incremental cancel still uploads what finished). _finish owns it.
        op._image_dir = worker.work_dir
        op._worker = None
        return op._cancel_render(context, state, op._collected)

    if stalled:
        logger.error("[Asset Training] Worker stalled — %s",
                     preview_worker.worker_exit_summary(worker))
        # One hung shard hangs the run: its assets never arrive, so the whole
        # fan-out is torn down (the next train re-renders the remainder).
        preview_worker.stop(worker)
        preview_worker.cleanup(worker)
        op._worker = None
        op._finish(context, success=False,
                   message="Background renderer stalled — try again")
        return {"CANCELLED"}

    if not done:
        return {"RUNNING_MODAL"}

    # Workers finished (or died). Nothing produced at all -> in-process fallback.
    if preview_worker.died_early(worker):
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

    # Everything was converted (and fed to the uploader) as it arrived.
    collected = op._collected
    # A shard that crashed after >=1 result leaves its remainder with NO
    # result line at all — record those as failures so complete() never
    # stamps the full-library checksum over unrendered assets (they would be
    # marked trained and never retried).
    failures = (op._worker_failures + worker.failures
                + preview_worker.missing_result_failures(worker))
    reused = sum(1 for r in worker.ok_results
                 if (r.get("info") or {}).get("reused_preview"))
    # Rendered because no thumbnail existed -> write the render back as the
    # asset's thumbnail in a DETACHED process, exactly like the in-process
    # path. Fire-and-forget: it re-saves .blend files and must not hold up the
    # upload (it copies the JPEGs it needs, so the dir below can go).
    launch_thumbnail_backfill(preview_worker.backfill_entries(worker))
    # The work dir holds the JPEGs the upload phase is about to read, so it is
    # handed to the operator instead of being removed here.
    op._image_dir = worker.work_dir
    op._worker = None
    return op._renders_complete(context, state, collected, failures,
                                reused=reused)
