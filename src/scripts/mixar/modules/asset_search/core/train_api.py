# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Training network layer — prepare + BATCHED image upload.

Runs in background threads (no ``bpy`` access). The upload is split into
batches so (a) upload/server-embedding progress ticks in real time instead of
one opaque multi-minute POST, and (b) a failure mid-way loses only the current
batch — everything already uploaded is durable and the next training run's
/train/prepare diff resumes from there.

Batching contract with the backend:
- ``full`` mode: batch 1 is sent mode="full" (replaces the old index), batches
  2+ ride mode="incremental" — net effect equals one full retrain.
- ``incremental`` mode: every batch is mode="incremental"; removed_assets go
  with batch 1 only.
- The full-library metadata_checksum is sent ONLY with the LAST batch: it must
  not be stamped until every asset is in, so an interrupted run reads as stale
  (diff-recoverable), never as complete.
"""

import json
import os

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.core.api_client import metered_client
from mixar.modules.asset_search.constants import (
    ASSET_TRAIN_ENDPOINT,
    ASSET_TRAIN_PREPARE_ENDPOINT,
)

logger = get_logger(__name__)

# Images per training POST. Matches the server's per-request ceiling
# (MAX_TRAIN_IMAGES = 500) so a typical library trains in ONE request. The
# endpoint is rate-limited (5/minute; 30/hour) AND credit-metered PER REQUEST,
# so a smaller batch multiplies the charge — 1000 assets went from 2 charges to
# 10 while it was briefly lowered to 100.
UPLOAD_BATCH_SIZE = 500
# And a byte ceiling under the server's 300MB/request cap, so an unusually large
# set of previews splits before it 413s. Whichever cap trips first ends a batch.
UPLOAD_BATCH_MAX_BYTES = 250 * 1024 * 1024


def train_client():
    """No-retry client for the training endpoints (see core/api_client)."""
    return metered_client()


def prepare_api(metadata, operator):
    """POST metadata to /train/prepare; result into ``operator._bg_result``."""
    try:
        client = train_client()
        resp = client.post(
            ASSET_TRAIN_PREPARE_ENDPOINT,
            data={"metadata": json.dumps(metadata)},
            timeout=30,
            raise_for_status=False,
        )
        if not resp.success:
            msg = resp.message or f"Server returned {resp.status_code}"
            operator._bg_result = {"success": False, "message": msg}
            return
        data = resp.data or {}
        inner = data.get("data", data)
        operator._bg_result = {
            "success": True,
            "action": inner.get("action", "full_train"),
            "new_assets": inner.get("new_assets", []),
            "removed_assets": inner.get("removed_assets", []),
            "asset_count": inner.get("asset_count", 0),
            "unchanged_count": inner.get("unchanged_count", 0),
            "metadata_checksum": inner.get("metadata_checksum"),
        }
    except Exception as exc:
        logger.error("[Asset Training] Prepare error: %s", exc)
        operator._bg_result = {"success": False, "message": f"Prepare failed: {exc}"}


def build_upload_batches(assets):
    """Split assets into upload batches, referencing previews by PATH.

    The JPEGs stay on disk and are read one batch at a time in
    ``post_batches`` — holding every preview's bytes in memory at once (a
    packed datablock AND a bytes copy per asset) was the peak-memory spike of a
    large training run.

    Args:
        assets: metadata dicts, each with ``image_name`` (the server's pairing
            key) and ``image_path`` (the JPEG on disk).

    Returns:
        List of {"metadata": [...], "files": [(filename, path), ...]}.
        Assets whose image is missing are dropped (already counted as failures).
    """
    batches = []
    cur_meta, cur_files, cur_bytes = [], [], 0
    for info in assets:
        path = info.get("image_path")
        if not info.get("image_name") or not path:
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        # Flush before adding an item that would exceed EITHER cap — but never
        # emit an empty batch (a single oversized item still ships alone).
        if cur_meta and (
            len(cur_meta) >= UPLOAD_BATCH_SIZE
            or cur_bytes + size > UPLOAD_BATCH_MAX_BYTES
        ):
            batches.append({"metadata": cur_meta, "files": cur_files})
            cur_meta, cur_files, cur_bytes = [], [], 0
        cur_meta.append(info)
        cur_files.append((f"{info['image_name']}.jpg", path))
        cur_bytes += size
    if cur_meta:
        batches.append({"metadata": cur_meta, "files": cur_files})
    return batches


def _read_batch_files(files):
    """Read one batch's JPEGs into the multipart shape requests expects.

    Bytes rather than open handles ON PURPOSE: HTTPClient re-sends `files`
    verbatim when it retries after a 401 refresh, and a consumed file object
    would upload an empty image on that second attempt.
    """
    payload = []
    for fname, path in files:
        try:
            with open(path, "rb") as fh:
                payload.append(("images", (fname, fh.read(), "image/jpeg")))
        except OSError as exc:
            logger.warning("[Asset Training] Skipping unreadable preview %s: %s",
                           path, exc)
    return payload


def post_batches(batches, mode, removed_assets, metadata_checksum, operator):
    """Upload every batch sequentially, reporting progress onto ``operator``.

    Progress fields (read by the training modal each tick):
      operator._upload_done / operator._upload_total  — batch counters
      operator._upload_embedded                       — images embedded so far
    Final result in ``operator._bg_result``.
    """
    operator._upload_total = max(len(batches), 1)
    operator._upload_done = 0
    operator._upload_embedded = 0

    try:
        client = train_client()

        if not batches:
            # Removal-only request.
            resp = client.post(
                ASSET_TRAIN_ENDPOINT,
                data={
                    "mode": "incremental",
                    "removed_assets": json.dumps(removed_assets),
                    "metadata": "[]",
                    **({"metadata_checksum": metadata_checksum}
                       if metadata_checksum else {}),
                },
                timeout=300,
                raise_for_status=False,
            )
            if not resp.success:
                msg = resp.message or f"Server returned {resp.status_code}"
                operator._bg_result = {"success": False, "message": msg}
                return
            inner = (resp.data or {}).get("data", resp.data or {})
            operator._upload_done = 1
            operator._bg_result = {
                "success": True,
                "message": f"{inner.get('removed', len(removed_assets))} removed",
                "embedded": 0,
            }
            return

        total_embedded = 0
        for i, batch in enumerate(batches):
            is_first = i == 0
            is_last = i == len(batches) - 1
            form_data = {
                # Only the FIRST batch may replace (full); the rest accumulate.
                "mode": mode if is_first else "incremental",
                "removed_assets": json.dumps(removed_assets if is_first else []),
                "metadata": json.dumps(batch["metadata"]),
            }
            # Stamp the full-library checksum only when everything is in.
            if is_last and metadata_checksum:
                form_data["metadata_checksum"] = metadata_checksum

            # Read THIS batch's images only; they are released before the next
            # batch is read, so peak memory stays at one batch.
            files_list = _read_batch_files(batch["files"])
            logger.debug(
                "[Asset Training] Uploading batch %d/%d (%d images)",
                i + 1, len(batches), len(files_list),
            )
            resp = client.post(
                ASSET_TRAIN_ENDPOINT,
                data=form_data,
                files=files_list,
                timeout=300,
                raise_for_status=False,
            )
            del files_list
            if not resp.success:
                msg = resp.message or f"Server returned {resp.status_code}"
                operator._bg_result = {
                    "success": False,
                    "message": (
                        f"Batch {i + 1}/{len(batches)} failed: {msg} — "
                        f"{total_embedded} assets were embedded before the "
                        "failure and are saved; run Train again to continue"
                    ),
                    "embedded": total_embedded,
                }
                return

            inner = (resp.data or {}).get("data", resp.data or {})
            total_embedded += int(inner.get("images_embedded", 0) or 0)
            operator._upload_done = i + 1
            operator._upload_embedded = total_embedded

        operator._bg_result = {
            "success": True,
            "message": f"{total_embedded} assets embedded",
            "embedded": total_embedded,
        }
    except Exception as exc:
        logger.error("[Asset Training] Upload error: %s", exc)
        operator._bg_result = {
            "success": False,
            "message": f"Upload failed: {exc}",
            "embedded": getattr(operator, "_upload_embedded", 0),
        }
