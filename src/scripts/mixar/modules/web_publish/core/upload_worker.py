# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Background publish pipeline.

Runs entirely on a daemon thread: init → upload (one presigned PUT, or
multipart parts with per-part retries) → complete → thumbnail. Progress
flows into ``PublishState``; the UI timer only reads. Every failure is
terminal-with-message, and the temp workspace is removed in ``finally``.
Never touches ``bpy``.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_
from mixar.modules.web_publish.constants import (
    GLB_CONTENT_TYPE,
    RETRY_BACKOFF_SECONDS,
    UPLOAD_PART_SIZE,
    UPLOAD_RETRIES_PER_PART,
)
from mixar.modules.web_publish.core import publish_api
from mixar.modules.web_publish.core.publish_api import PublishApiError, parse_scene_payload
from mixar.modules.web_publish.core.publish_state import (
    STATUS_FINALIZING,
    STATUS_UPLOADING,
    PublishJob,
    PublishResult,
    get_publish_state,
    part_ranges,
)
from mixar.modules.web_publish.core.workspace import cleanup_workspace

_logger = get_logger(__name__)


# A cancel seen by the worker and one raised mid-PUT are the same outcome.
_Cancelled = publish_api.UploadCancelled


def spawn(job: PublishJob, workspace: str, service) -> bool:
    """Start the worker for a publish the caller claimed (``state.begin``)
    before its export. Reuses that claim — never re-claims — and refuses
    loudly (ERROR state, workspace removed) when there is no live claim."""
    state = get_publish_state()
    if not state.busy:
        cleanup_workspace(workspace)
        state.set_error(n_("The publish lost its claim before upload"))
        return False
    thread = threading.Thread(target=_run, args=(job, workspace, service),
                              name="mixar-web-publish", daemon=True)
    thread.start()
    return True


def _run(job: PublishJob, workspace: str, service) -> None:
    """Thread entry: every way out ends terminal, so the single publish
    slot is always released (a dead thread must never leave it busy)."""
    state = get_publish_state()
    created = {}
    try:
        try:
            _publish(job, service, state, created)
        except _Cancelled:
            _discard_draft(service, job, created)
            state.set_cancelled()
        except PublishApiError as exc:
            _discard_draft(service, job, created)
            state.set_error(exc.message, **exc.params)
    except BaseException as exc:  # noqa: BLE001 - incl. a failing handler above
        _logger.error("web_publish worker failed: %s", exc, exc_info=True)
        state.set_error(n_("Publish failed ({kind})"), kind=exc.__class__.__name__)
    finally:
        if state.busy:  # belt and braces: never leave the claim held
            state.set_error(n_("Publish failed ({kind})"), kind="unfinished")
        cleanup_workspace(workspace)


def _check_cancel(state) -> None:
    if state.cancel_requested:
        raise _Cancelled()


def _discard_draft(service, job: PublishJob, created: dict) -> None:
    """A cancelled or failed FIRST publish leaves a draft row (the backend's
    DELETE also aborts its pending multipart upload); a revision must never
    be deleted (that would unpublish the live site)."""
    scene_id = created.get("scene_id")
    if not scene_id or job.existing_scene_id:
        return
    try:
        service.delete_scene(scene_id)
    except Exception as exc:  # noqa: BLE001 - best-effort cleanup
        _logger.warning("web_publish draft cleanup failed: %s", exc)


def _publish(job: PublishJob, service, state, created: dict) -> None:
    _check_cancel(state)  # cancelled while the export ran
    size_bytes = os.path.getsize(job.glb_path)
    state.set_status(STATUS_UPLOADING, n_("Reserving your scene link…"), 0.02)
    init_body = {
        "title": job.title,
        "size_bytes": size_bytes,
        "content_sha256": job.content_sha256,
        "scene_meta": job.scene_meta,
        "viewer_config": job.viewer_config,
    }
    if job.description or not job.existing_scene_id:
        # An empty description on a new version is left out: the backend keeps
        # the site's description rather than clearing it.
        init_body["description"] = job.description or None
    if job.visibility:
        # Absent on an agent's new version: the backend keeps the site's access.
        init_body["visibility"] = job.visibility
    if job.existing_scene_id:
        # Revision of an existing scene: the id selects it (a foreign or
        # deleted id is a 404); the slug keeps older backends on the link.
        init_body["scene_id"] = job.existing_scene_id
    if job.existing_slug:
        init_body["slug"] = job.existing_slug

    scene, upload = service.init_publish(init_body)
    base_url = getattr(service, "base_url", "")
    payload = parse_scene_payload(scene, base_url)
    created["scene_id"] = payload["id"]
    mode = str(upload.get("mode") or "")

    if mode == "dedup":
        # Identical bytes already stored: the record was repointed.
        _attach_thumbnail(service, state, job, payload["id"])
        state.set_result(_result(payload), n_("Published (content unchanged)"))
        return

    _check_cancel(state)
    state.set_status(STATUS_UPLOADING, n_("Uploading scene…"), 0.05)
    parts = upload_id = None
    if mode == "put":
        publish_api.put_object(upload["url"], job.glb_path, size_bytes, GLB_CONTENT_TYPE,
                               on_progress=_reporter(state, 0.05, 0.85),
                               should_cancel=lambda: state.cancel_requested)
    elif mode == "multipart":
        parts, upload_id = _upload_multipart(upload, job.glb_path, size_bytes, state)
    else:
        raise PublishApiError(n_("The server returned an unsupported upload mode"),
                              code="bad_upload_plan")

    _check_cancel(state)
    state.set_status(STATUS_UPLOADING, n_("Finishing upload…"), 0.92)
    payload = parse_scene_payload(
        service.complete_upload(payload["id"], upload_id, parts, job.content_sha256),
        base_url)
    _attach_thumbnail(service, state, job, payload["id"])
    state.set_result(_result(payload), n_("Published at /s/{slug}"), slug=payload["slug"])


def _result(payload: dict) -> PublishResult:
    return PublishResult(scene_id=payload["id"], slug=payload["slug"],
                         share_url=payload["share_url"], viewer_url=payload["viewer_url"],
                         revision=payload["revision"])


def _attach_thumbnail(service, state, job: PublishJob, scene_id: str) -> None:
    """Thumbnail failure never fails the publish."""
    if not (job.thumbnail_path and os.path.isfile(job.thumbnail_path) and scene_id):
        return
    try:
        state.set_status(STATUS_FINALIZING, n_("Uploading thumbnail…"), 0.96)
        service.upload_thumbnail(scene_id, job.thumbnail_path)
    except (PublishApiError, OSError) as exc:
        _logger.warning("web_publish thumbnail upload failed: %s", exc)


def _upload_multipart(upload, glb_path, size_bytes, state):
    upload_id = upload.get("upload_id") or ""
    part_size = int(upload.get("part_size_bytes") or UPLOAD_PART_SIZE)
    part_urls = {int(p["part_number"]): p["url"] for p in upload.get("parts") or []}
    if not upload_id or not part_urls:
        raise PublishApiError(n_("The server returned an incomplete upload plan"),
                              code="bad_upload_plan")
    ranges = part_ranges(size_bytes, part_size)
    if len(ranges) != len(part_urls):
        raise PublishApiError(n_("The upload plan does not match the scene size"),
                              code="bad_upload_plan")
    parts = []
    for index, (part_number, offset, length) in enumerate(ranges):
        _check_cancel(state)
        url = part_urls.get(part_number)
        if not url:
            raise PublishApiError(n_("The upload plan is missing a part"),
                                  code="bad_upload_plan")
        base = 0.05 + 0.85 * (index / len(ranges))
        state.set_status(STATUS_UPLOADING, n_("Uploading part {index} of {count}…"), base,
                         index=index + 1, count=len(ranges))
        etag = _put_part_with_retry(url, glb_path, offset, length, state,
                                    _reporter(state, base, 0.85 / len(ranges)), part_number)
        parts.append({"part_number": part_number, "etag": etag})
    return parts, upload_id


def _put_part_with_retry(url, path, offset, length, state, on_progress, part_number):
    last_error: Optional[Exception] = None
    for attempt in range(1, UPLOAD_RETRIES_PER_PART + 1):
        _check_cancel(state)
        try:
            return publish_api.put_part(url, path, offset, length, on_progress=on_progress)
        except (PublishApiError, OSError) as exc:
            last_error = exc
            _logger.warning("web_publish part %s attempt %s failed: %s",
                            part_number, attempt, exc)
            if attempt < UPLOAD_RETRIES_PER_PART:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    if isinstance(last_error, PublishApiError) and last_error.code == "network":
        raise last_error
    raise PublishApiError(n_("Upload failed after {attempts} attempts"), code="upload_failed",
                          params={"attempts": UPLOAD_RETRIES_PER_PART})


def _reporter(state, base: float, span: float):
    """Map a byte count onto ``[base, base + span]`` of the overall bar."""
    def report(done_bytes: int, total_bytes: int) -> None:
        fraction = base + span * (done_bytes / max(total_bytes, 1))
        state.set_status(STATUS_UPLOADING, progress=fraction)

    return report
