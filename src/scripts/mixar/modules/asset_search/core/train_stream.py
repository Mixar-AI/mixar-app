# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Streaming uploads — send finished previews WHILE rendering continues.

Training used to render every asset, then upload. The two phases are
independent (rendering is local CPU, uploading is network + server-side
embedding), so a large run spent minutes rendering with the network idle and
then minutes uploading with the CPU idle. Here the render loop hands finished
assets to a ``BatchBuilder`` as they land and ONE uploader thread posts each
batch as it fills, so the upload cost disappears into the render time.

Ordering is strictly sequential and matters: batch 1 may carry ``mode=full``
(which REPLACES the user's index) plus the removed-asset list, and the batch
carrying ``metadata_checksum`` must be the LAST one — the checksum marks the
library fully embedded, so stamping it early would mark un-uploaded assets as
trained. ``BatchBuilder`` therefore holds the newest completed batch back until
another one exists, which makes the final batch knowable without spending an
extra credit-metered request just to stamp the checksum.
"""

import json
import os
import threading
import time
from collections import deque

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.constants import ASSET_TRAIN_ENDPOINT
from mixar.modules.asset_search.core.train_api import (
    UPLOAD_BATCH_MAX_BYTES,
    UPLOAD_BATCH_SIZE,
    _read_batch_files,
    train_client,
)

logger = get_logger(__name__)

# The /train endpoint is rate-limited to 5 requests per minute (and metered per
# request). Back-to-back posting was safe while uploads only started after
# every render finished; streaming can produce batches much faster than that,
# so the uploader paces itself rather than eating a 429 mid-run.
RATE_LIMIT_POSTS = 5
RATE_LIMIT_WINDOW = 60.0


class BatchStream:
    """Thread-safe hand-off of upload batches to a single uploader thread."""

    def __init__(self):
        self._batches = deque()
        self._closed = False
        self._aborted = False
        self._cv = threading.Condition()

    def push(self, batch):
        with self._cv:
            self._batches.append(batch)
            self._cv.notify()

    def close(self):
        """No more batches are coming; the consumer drains and stops."""
        with self._cv:
            self._closed = True
            self._cv.notify()

    def abort(self):
        """Stop the consumer NOW, dropping anything still queued."""
        with self._cv:
            self._aborted = True
            self._closed = True
            self._cv.notify()

    @property
    def aborted(self):
        with self._cv:
            return self._aborted

    def pop(self, timeout=0.5):
        """Next batch, or None once the stream is closed AND drained.

        Blocks while the producer is still rendering — a starved consumer is
        the normal state, not an error.
        """
        with self._cv:
            while not self._batches and not self._closed:
                self._cv.wait(timeout)
            if self._aborted:
                return None
            return self._batches.popleft() if self._batches else None


class BatchBuilder:
    """Accumulates finished assets into batches and pushes them to a stream.

    The most recently completed batch is HELD BACK until another one exists, so
    ``close()`` always has a real batch to attach the metadata_checksum to.
    """

    def __init__(self, stream):
        self._stream = stream
        self._meta = []
        self._files = []
        self._bytes = 0
        self._held = None
        self.batches_built = 0

    def add(self, infos):
        """Queue finished assets (metadata dicts with image_name/image_path)."""
        for info in infos:
            path = info.get("image_path")
            if not info.get("image_name") or not path:
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            # Flush before adding an item that would exceed EITHER cap — but
            # never emit an empty batch (a single oversized item ships alone).
            if self._meta and (
                len(self._meta) >= UPLOAD_BATCH_SIZE
                or self._bytes + size > UPLOAD_BATCH_MAX_BYTES
            ):
                self._flush()
            self._meta.append(info)
            self._files.append((f"{info['image_name']}.jpg", path))
            self._bytes += size

    def _flush(self):
        batch = {"metadata": self._meta, "files": self._files}
        self._meta, self._files, self._bytes = [], [], 0
        self.batches_built += 1
        if self._held is not None:
            self._stream.push(self._held)
        self._held = batch

    def close(self, metadata_checksum):
        """Push what is left; the LAST batch carries the checksum."""
        if self._meta:
            self._flush()
        last, self._held = self._held, None
        if last is not None:
            if metadata_checksum:
                last["checksum"] = metadata_checksum
            self._stream.push(last)
        self._stream.close()
        return self.batches_built


class _Pacer:
    """Keeps posts within the endpoint's requests-per-window budget."""

    def __init__(self, limit=RATE_LIMIT_POSTS, window=RATE_LIMIT_WINDOW):
        self._stamps = deque()
        self._limit = limit
        self._window = window

    def wait(self):
        now = time.monotonic()
        while self._stamps and now - self._stamps[0] > self._window:
            self._stamps.popleft()
        if len(self._stamps) >= self._limit:
            delay = self._window - (now - self._stamps[0]) + 0.5
            if delay > 0:
                logger.debug("[Asset Training] Pacing upload: %.1fs", delay)
                time.sleep(delay)
        self._stamps.append(time.monotonic())


def post_stream(stream, mode, removed_assets, operator):
    """Post batches as they arrive from ``stream``; report onto ``operator``.

    Same wire protocol as the non-streaming ``post_batches``: the first request
    carries ``mode`` and the removed-asset list, every later one is
    incremental, and the metadata_checksum rides the final batch (attached by
    ``BatchBuilder.close``). A failed batch stops the run — everything already
    uploaded is durable server-side and the next train's diff resumes from it.
    """
    operator._upload_done = 0
    operator._upload_embedded = 0
    pacer = _Pacer()
    sent = 0
    total_embedded = 0

    try:
        client = train_client()
        while True:
            batch = stream.pop()
            if batch is None:
                break

            form_data = {
                # Only the FIRST request may replace (full); the rest accumulate.
                "mode": mode if sent == 0 else "incremental",
                "removed_assets": json.dumps(removed_assets if sent == 0 else []),
                "metadata": json.dumps(batch["metadata"]),
            }
            if batch.get("checksum"):
                form_data["metadata_checksum"] = batch["checksum"]

            files_list = _read_batch_files(batch["files"])
            pacer.wait()
            logger.debug("[Asset Training] Uploading streamed batch %d (%d images)",
                         sent + 1, len(files_list))
            resp = client.post(
                ASSET_TRAIN_ENDPOINT,
                data=form_data,
                files=files_list,
                timeout=300,
                raise_for_status=False,
            )
            del files_list

            if not resp.success:
                # Report the status code alongside the server's detail: with
                # retries off this IS the server's own answer, and knowing
                # 500 vs 413 vs 429 is the difference between "batch too big",
                # "too many requests" and "the endpoint broke".
                msg = resp.message or "no detail"
                logger.error(
                    "[Asset Training] Batch %d rejected (%s): %s",
                    sent + 1, resp.status_code, msg,
                )
                stream.abort()
                operator._bg_result = {
                    "success": False,
                    "message": (
                        f"Batch {sent + 1} failed ({resp.status_code}): {msg} — "
                        f"{total_embedded} assets were embedded before the "
                        "failure and are saved; run Train again to continue"
                    ),
                    "embedded": total_embedded,
                }
                return

            inner = (resp.data or {}).get("data", resp.data or {})
            total_embedded += int(inner.get("images_embedded", 0) or 0)
            sent += 1
            operator._upload_done = sent
            operator._upload_embedded = total_embedded

        if sent == 0:
            # Nothing was rendered — but removals still have to reach the
            # server (and carry the checksum), same as the batch-less path in
            # post_batches.
            if removed_assets:
                resp = client.post(
                    ASSET_TRAIN_ENDPOINT,
                    data={
                        "mode": "incremental",
                        "removed_assets": json.dumps(removed_assets),
                        "metadata": "[]",
                        **({"metadata_checksum": operator._metadata_checksum}
                           if operator._metadata_checksum else {}),
                    },
                    timeout=300,
                    raise_for_status=False,
                )
                if not resp.success:
                    operator._bg_result = {
                        "success": False,
                        "message": resp.message or f"Server returned {resp.status_code}",
                    }
                    return
                operator._upload_done = 1
                operator._bg_result = {
                    "success": True,
                    "message": f"{len(removed_assets)} removed",
                    "embedded": 0,
                }
                return
            operator._bg_result = {
                "success": True, "message": "Nothing to upload", "embedded": 0,
            }
            return

        operator._bg_result = {
            "success": True,
            "message": f"{total_embedded} assets embedded",
            "embedded": total_embedded,
        }
    except Exception as exc:  # noqa: BLE001 — the modal must always finish
        logger.error("[Asset Training] Streamed upload error: %s", exc)
        stream.abort()
        operator._bg_result = {
            "success": False,
            "message": f"Upload failed: {exc}",
            "embedded": total_embedded,
        }
