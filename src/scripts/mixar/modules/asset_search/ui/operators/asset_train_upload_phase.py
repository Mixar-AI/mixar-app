# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Upload half of the training modal (split from asset_train_ops for file size).

Two ways in:

* **Streamed** (the normal path) — the uploader thread starts with the render
  phase and posts each batch as it fills, so the network works while the
  remaining assets render. ``core/train_stream`` owns the protocol.
* **Barrier** (``UPLOADING`` phase) — render everything, build every batch, then
  post. Kept for the one case streaming is unsafe: a full train started because
  /train/prepare FAILED, where an existing index might be silently replaced by
  a run the user could still cancel.

Both end in ``WAITING``, which just watches the thread and reports progress.
"""

import threading

from mixar.modules.asset_search.core.train_api import build_upload_batches, post_batches
from mixar.modules.asset_search.core.train_support import W_RENDER_END

from .asset_inspect_ops import get_collected_asset_data


def start_stream(op):
    """Open the batch stream and start the single uploader thread."""
    if not op._stream_uploads:
        return
    from mixar.modules.asset_search.core.train_stream import (
        BatchBuilder, BatchStream, post_stream,
    )

    op._stream = BatchStream()
    op._builder = BatchBuilder(op._stream)
    op._bg_result = None
    op._bg_thread = threading.Thread(
        target=post_stream,
        args=(op._stream, op._train_mode, op._removed_assets, op),
        daemon=True,
    )
    op._bg_thread.start()


def feed(op, infos):
    """Record finished assets and queue them for upload (streaming only)."""
    if not infos:
        return
    op._collected.extend(infos)
    if op._builder is not None and not op._stream.aborted:
        op._builder.add(infos)


def note(op):
    """' · uploaded N' for the render phase text, or '' before the first post."""
    return f" · uploaded {op._upload_done}" if op._upload_done else ""


def stop_stream(op, drop=False):
    """End the stream. ``drop`` abandons anything not yet posted."""
    if op._stream is None:
        return
    if drop:
        op._stream.abort()
    elif op._builder is not None:
        # close() pushes the held-back final batch (carrying the checksum) and
        # returns the batch count — only now is the total known, so this is
        # what the WAITING phase reports progress against.
        op._upload_total = max(op._builder.close(op._metadata_checksum), 1)
    else:
        op._stream.close()
    op._builder = None


def handle_uploading(op, context, state):
    """Barrier path: build every batch, then post them on one thread."""
    # Previews live on disk (info["image_path"]); build_upload_batches bounds
    # each batch by file SIZE and post_batches reads the bytes one batch at a
    # time, so peak memory is one batch — not the whole library.
    batches = build_upload_batches(get_collected_asset_data())
    if not batches and not op._removed_assets and op._train_mode == "full":
        op._finish(context, success=False, message="No images to upload")
        return {"FINISHED"}

    state.upload_total = max(len(batches), 1)
    state.upload_done = 0
    state.phase_text = f"Uploading & embedding — batch 0/{max(len(batches), 1)}"

    op._bg_result = None
    op._bg_thread = threading.Thread(
        target=post_batches,
        args=(batches, op._train_mode, op._removed_assets,
              op._metadata_checksum, op),
        daemon=True,
    )
    op._bg_thread.start()
    op._phase = 'WAITING'
    op._redraw(context)
    return {"RUNNING_MODAL"}


def handle_waiting(op, context, state):
    """Watch the uploader thread and report its progress."""
    done, total = op._upload_done, max(op._upload_total, 1)
    if done != state.upload_done or state.upload_total != total:
        state.upload_done = done
        state.upload_total = total
        state.phase_text = f"Uploading & embedding — batch {done}/{total}"
        state.progress = W_RENDER_END + (1.0 - W_RENDER_END) * (done / total)
        op._redraw(context)

    if op._bg_thread and op._bg_thread.is_alive():
        return {"RUNNING_MODAL"}

    res = op._bg_result or {}
    success = res.get("success", False)
    state.progress = 1.0
    if success:
        state.needs_retraining = False
        state.retraining_message = ""
    op._finish(context, success=success,
               message=res.get("message", "API upload failed"))
    return {"FINISHED"}
