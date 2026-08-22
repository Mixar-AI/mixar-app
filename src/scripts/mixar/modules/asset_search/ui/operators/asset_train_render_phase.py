# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render half of the training modal (split from asset_train_ops for file size).

Plans the work, picks the renderer (headless workers for big plans, the
in-process chunked session otherwise — see asset_train_worker_phase for the
former), drives the in-process ticks, and owns what completion and cancellation
mean. Finished assets are handed to the uploader AS THEY LAND, so the network
works while the remaining assets render.
"""

import time

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.core import preview_worker
from mixar.modules.asset_search.core.train_support import (
    W_PREPARE_END,
    W_RENDER_END,
    fmt_duration,
    set_failures,
)

from .asset_inspect_ops import (
    clear_render_filter,
    get_render_filter,
    set_collected_asset_data,
    set_render_filter,
)

logger = get_logger(__name__)


def start_rendering(op, context, state, filter_assets):
    """Build the plan and hand it to the worker fan-out or the in-process session."""
    from mixar.modules.asset_search.core.render_session import build_render_plan

    if filter_assets is not None:
        set_render_filter(filter_assets)
    else:
        clear_render_filter()

    items, discovery_failures = build_render_plan(context, get_render_filter())
    if not items and op._train_mode == "full":
        op._finish(context, success=False,
                   message="No objects or collections found in asset libraries")
        return {"CANCELLED"}

    state.assets_total = len(items)
    state.assets_done = 0
    state.progress = W_PREPARE_END
    op._render_started_at = time.time()
    op._worker_failures = list(discovery_failures)
    # Open the upload stream BEFORE rendering starts: batches go out as they
    # fill, so the upload cost hides inside the render time.
    op._start_upload_stream()

    if len(items) >= preview_worker.WORKER_MIN_ITEMS:
        op._worker = preview_worker.start_worker(items)
        if op._worker is not None:
            state.phase_text = (
                f"Rendering previews in background 0/{len(items)} "
                "(app stays responsive)"
            )
            op._phase = 'RENDER_WORKER'
            op._redraw(context)
            return {"RUNNING_MODAL"}
        logger.warning("[Asset Training] Worker unavailable — in-process render")

    return start_inprocess_session(op, context, state, items)


def start_inprocess_session(op, context, state, items):
    from mixar.modules.asset_search.core.render_session import RenderSession

    op._session = RenderSession(context, items)
    # Same contract as the worker path: the previews are files, and this run
    # owns their directory until the upload is done.
    op._image_dir = op._session.out_dir
    op._session.failures.extend(op._worker_failures)
    op._worker_failures = []
    op._session.start()
    state.phase_text = f"Rendering previews 0/{len(items)}"
    op._phase = 'RENDERING'
    op._redraw(context)
    return {"RUNNING_MODAL"}


def update_progress(op, state, done, total, current):
    state.assets_done = done
    state.assets_total = total
    state.current_item = current
    frac = done / total if total else 1.0
    state.progress = W_PREPARE_END + (W_RENDER_END - W_PREPARE_END) * frac
    elapsed = time.time() - op._render_started_at
    if 3 <= done < total:
        state.eta_text = f"~{fmt_duration((elapsed / done) * (total - done))} remaining"


def handle_rendering(op, context, state):
    """One modal tick of the in-process RENDERING phase."""
    session = op._session
    if state.cancel_requested and not session.done:
        return cancel(op, context, state, session.collected,
                      teardown=session.finish)
    if not session.done:
        session.step()
        # Hand whatever finished this tick to the uploader.
        op._feed_collected(session.collected[len(op._collected):])
        update_progress(op, state, session.index, session.total,
                        session.current_label)
        set_failures(state, session.failures)
        state.phase_text = (
            f"Rendering previews {session.index}/{session.total}"
            + op._upload_note()
        )
        op._redraw(context)
        return {"RUNNING_MODAL"}

    session.finish()
    op._feed_collected(session.collected[len(op._collected):])
    # Rendered because no thumbnail existed -> write the render back as the
    # asset's thumbnail (fire-and-forget worker; never blocks).
    if session.rendered_items:
        from mixar.modules.asset_search.core.train_support import (
            launch_thumbnail_backfill,
        )
        launch_thumbnail_backfill(session.rendered_items)
    return complete(op, context, state, op._collected, session.failures,
                    reused=session.preview_reused)


def complete(op, context, state, collected, failures, reused=0):
    """Rendering finished — close the stream, or fall back to the barrier upload."""
    set_collected_asset_data(collected)
    clear_render_filter()
    set_failures(state, failures)
    state.current_item = ""
    state.eta_text = ""
    # The full-library checksum marks the library FULLY embedded at this
    # content hash — the server then returns "skip" on the next train. Never
    # stamp it when assets are still un-embedded (any render/embed failure), or
    # those assets are marked trained and become unreachable until the
    # library's contents change. A clean run stamps it; a partial run leaves it
    # unstamped so the next train retries the remainder.
    if failures:
        op._metadata_checksum = None
    if reused:
        state.prepare_note = (
            (state.prepare_note + " · " if state.prepare_note else "")
            + f"{reused} thumbnails reused (not re-rendered)"
        )

    if not collected and op._train_mode == "full":
        op._stop_upload_stream(drop=True)
        op._finish(context, success=False, message="No assets could be rendered")
        return {"CANCELLED"}
    state.progress = W_RENDER_END
    if op._stream_uploads:
        # Batches have been going out all along; closing the stream sends the
        # held-back final one (with the checksum) and ends the thread.
        op._stop_upload_stream()
        state.phase_text = "Finishing upload & embedding…"
        op._phase = 'WAITING'
    else:
        op._phase = 'UPLOADING'
    op._redraw(context)
    return {"RUNNING_MODAL"}


def cancel(op, context, state, collected, teardown=None):
    """Incremental keeps finished work (durable server-side); an unstreamed full
    run discards — a partial mode="full" upload would REPLACE the index. A
    STREAMED run has already sent batches, so its finished work is kept too
    (streaming is only enabled where that is safe: an incremental run, or a
    full_train the server told us has no existing index)."""
    if teardown is not None:
        teardown()
    clear_render_filter()

    # A cancelled run is partial by definition: keep the finished assets
    # (incremental uploads are durable server-side) but NEVER stamp the
    # full-library checksum, or the un-rendered remainder is marked trained and
    # never retried.
    op._metadata_checksum = None

    keep = collected and (op._train_mode == "incremental" or op._stream_uploads)
    if keep:
        set_collected_asset_data(collected)
        state.phase_text = (
            f"Cancelled — saving the {len(collected)} finished assets…"
        )
        state.progress = W_RENDER_END
        if op._stream_uploads:
            op._stop_upload_stream()
            op._phase = 'WAITING'
        else:
            op._phase = 'UPLOADING'
        op._redraw(context)
        return {"RUNNING_MODAL"}

    set_collected_asset_data([])
    op._stop_upload_stream(drop=True)
    op._finish(context, success=False,
               message="Training cancelled — nothing was changed")
    return {"CANCELLED"}
