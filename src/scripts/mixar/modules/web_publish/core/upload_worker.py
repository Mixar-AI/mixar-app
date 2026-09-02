# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Background publish pipeline.

Runs entirely on a daemon thread: init → upload (PUT or multipart parts) →
thumbnail → complete. Progress flows into PublishState; the UI timer only
reads. Every network failure is terminal-with-message — the local GLB stays
on disk so a retry never re-exports unless the scene changed.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from mixar.config.logging_config import get_logger
from mixar.modules.web_publish.constants import (
    RETRY_BACKOFF_SECONDS,
    UPLOAD_PART_SIZE,
    UPLOAD_RETRIES_PER_PART,
)
from mixar.modules.web_publish.core.publish_api import (
    PublishApiError,
    ScenePublishClient,
    parse_scene_payload,
)
from mixar.modules.web_publish.core.publish_state import (
    STATUS_EXPORTING,
    STATUS_FINALIZING,
    STATUS_UPLOADING,
    PublishJob,
    PublishResult,
    part_ranges,
    get_publish_state,
)

_logger = get_logger(__name__)


def start_publish(job: PublishJob, workspace: str) -> bool:
    """Spawn the worker thread. Returns False when one is already running."""
    state = get_publish_state()
    if state.busy:
        return False
    state.start()
    thread = threading.Thread(
        target=_run,
        args=(job, workspace),
        name="mixar-web-publish",
        daemon=True,
    )
    thread.start()
    return True


def _run(job: PublishJob, workspace: str) -> None:
    state = get_publish_state()
    client = ScenePublishClient()
    try:
        _publish(job, workspace, client, state)
    except PublishApiError as exc:
        state.set_error(exc.message)
    except Exception as exc:  # noqa: BLE001 - worker must never crash silently
        _logger.error(f"web_publish worker failed: {exc}", exc_info=True)
        state.set_error(f"Publish failed: {exc}")


def _publish(job: PublishJob, workspace: str, client: ScenePublishClient, state) -> None:
    glb_path = job.glb_path
    size_bytes = os.path.getsize(glb_path)

    state.set_status(STATUS_EXPORTING, "Reserving your scene URL…", 0.02)
    init_body = {
        "title": job.title,
        "description": job.description or None,
        "visibility": job.visibility,
        "size_bytes": size_bytes,
        "content_sha256": job.content_sha256,
        "scene_meta": job.scene_meta,
        "viewer_config": job.viewer_config,
    }
    if job.existing_scene_id:
        # Revision of an existing scene — carry its slug so the URL is stable.
        init_body["slug"] = job.existing_slug

    scene, upload = client.init_publish(init_body)
    scene_payload = parse_scene_payload(scene)

    mode = str(upload.get("mode") or "")

    if mode == "dedup":
        # Identical bytes already stored — the record was repointed.
        state.set_status(STATUS_UPLOADING, "Scene unchanged — reusing stored copy", 0.6)
        scene_payload = _ensure_thumbnail(
            client, state, scene_payload, job, scene.get("id") or scene_payload["id"]
        )
        state.set_result(
            PublishResult(
                scene_id=scene_payload["id"],
                slug=scene_payload["slug"],
                share_url=scene_payload["share_url"],
                viewer_url=scene_payload["viewer_url"],
                revision=scene_payload["revision"],
            ),
            detail="Published (content unchanged)",
        )
        return

    state.set_status(STATUS_UPLOADING, "Uploading scene…", 0.05)
    if mode == "put":
        client.put_object(
            upload["url"], glb_path, size_bytes, "model/gltf-binary",
            on_progress=_progress_reporter(state, 0.05, 0.9),
        )
        parts = None
        upload_id = None
    elif mode == "multipart":
        parts, upload_id = _upload_multipart(
            client, upload, glb_path, size_bytes, state
        )
    else:
        raise PublishApiError(
            "Server returned an unsupported upload mode", code="bad_upload_plan"
        )

    state.set_status(STATUS_UPLOADING, "Finishing upload…", 0.92)
    scene_payload = parse_scene_payload(
        client.complete_upload(scene_payload["id"], upload_id, parts, job.content_sha256)
    )

    scene_payload = _ensure_thumbnail(client, state, scene_payload, job, scene_payload["id"])

    state.set_result(
        PublishResult(
            scene_id=scene_payload["id"],
            slug=scene_payload["slug"],
            share_url=scene_payload["share_url"],
            viewer_url=scene_payload["viewer_url"],
            revision=scene_payload["revision"],
        ),
        detail=f"Published at /s/{scene_payload['slug']}",
    )


def _ensure_thumbnail(client, state, scene_payload, job, scene_id):
    """Attach the thumbnail when the scene has none for this revision."""
    if job.thumbnail_path and os.path.isfile(job.thumbnail_path):
        try:
            state.set_status(STATUS_FINALIZING, "Uploading thumbnail…", 0.96)
            client.upload_thumbnail(scene_id, job.thumbnail_path)
        except PublishApiError as exc:
            # Thumbnail failure never fails the publish.
            _logger.warning(f"web_publish thumbnail upload failed: {exc.message}")
    return scene_payload


def _upload_multipart(client, upload, glb_path, size_bytes, state):
    upload_id = upload.get("upload_id") or ""
    part_size = int(upload.get("part_size_bytes") or UPLOAD_PART_SIZE)
    part_urls = {int(p["part_number"]): p["url"] for p in upload.get("parts") or []}
    if not upload_id or not part_urls:
        raise PublishApiError("Server returned an incomplete upload plan",
                              code="bad_upload_plan")

    ranges = part_ranges(size_bytes, part_size)
    if len(ranges) != len(part_urls):
        raise PublishApiError(
            "Upload plan does not match the scene size", code="bad_upload_plan"
        )

    parts = []
    base = 0.05
    span = 0.85
    for index, (part_number, offset, length) in enumerate(ranges):
        if get_publish_state().cancel_requested:
            raise PublishApiError("Publish cancelled", code="cancelled")
        url = part_urls.get(part_number)
        if not url:
            raise PublishApiError("Missing presigned URL for a part",
                                  code="bad_upload_plan")
        fraction = base + span * (index / max(len(ranges), 1))
        state.set_status(
            STATUS_UPLOADING,
            f"Uploading part {index + 1} of {len(ranges)}…",
            fraction,
        )
        etag = _put_part_with_retry(
            client, url, glb_path, offset, length, state, part_number, len(ranges)
        )
        parts.append({"part_number": part_number, "etag": etag})
    return parts, upload_id


def _put_part_with_retry(client, url, path, offset, length, state,
                         part_number, total_parts):
    last_error: Optional[Exception] = None
    for attempt in range(1, UPLOAD_RETRIES_PER_PART + 1):
        try:
            progress_base = 0.05 + 0.85 * ((part_number - 1) / max(total_parts, 1))
            progress_span = 0.85 / max(total_parts, 1)
            return client.put_part(
                url, path, offset, length,
                on_progress=_part_progress_reporter(
                    state, progress_base, progress_span
                ),
            )
        except (PublishApiError, OSError) as exc:
            last_error = exc
            _logger.warning(
                f"web_publish part {part_number} attempt {attempt} failed: {exc}"
            )
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise PublishApiError(
        f"Upload failed after {UPLOAD_RETRIES_PER_PART} attempts: {last_error}",
        code="upload_failed",
    )


def _progress_reporter(state, base: float, span: float):
    def report(done_bytes: int, total_bytes: int) -> None:
        fraction = base + span * (done_bytes / max(total_bytes, 1))
        state.set_upload_progress(done_bytes, total_bytes)
        state.set_status(STATUS_UPLOADING, "Uploading scene…", fraction)

    return report


def _part_progress_reporter(state, base: float, span: float):
    def report(done_bytes: int, total_bytes: int) -> None:
        state.set_upload_progress(done_bytes, total_bytes)

    return report
