# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Installer Download

Streams the release installer into the staging directory, verifying it
against the ``sha256`` the backend published before the file is given its
final name.  Imports no ``bpy`` — every callback fires on the download
thread and callers must marshal to the main thread themselves.

Three properties matter here and each is deliberate:

- **The checksum gates the filename.**  Bytes land in ``<name>.part`` and
  are renamed only after the digest matches, so a staged installer is
  never a truncated or tampered one.  We are about to run this file
  elevated; "probably finished downloading" is not good enough.
- **Transfers resume.**  Installers are 400 MB-plus and a dropped
  connection three quarters of the way through must not restart from
  zero, so a retry sends a ``Range`` header and keeps the running digest.
  A server that ignores the range and replays the whole body is handled
  by resetting both file and digest.
- **The budget is bounded.**  ``urlopen(timeout=...)`` is a per-read
  timeout that a trickling connection resets forever, so a total deadline
  is enforced between chunks.
"""

import hashlib
import os
import time
import urllib.error
import urllib.request

from mixar.config.logging_config import get_logger

from ..constants import (
    DOWNLOAD_CHUNK_BYTES,
    DOWNLOAD_MAX_ATTEMPTS,
    DOWNLOAD_PROGRESS_INTERVAL_S,
    DOWNLOAD_RETRY_BACKOFF_FACTOR,
    DOWNLOAD_RETRY_BACKOFF_S,
    DOWNLOAD_SOCKET_TIMEOUT_S,
    DOWNLOAD_TOTAL_DEADLINE_S,
    PARTIAL_SUFFIX,
)

logger = get_logger(__name__)

_BACKOFF_SLICE_S = 0.25


class UpdateDownloadError(Exception):
    """A download or verification failure. ``user_message`` is UI-safe."""

    def __init__(self, message, user_message="", retryable=False):
        super().__init__(message)
        self.user_message = user_message or "Download failed"
        self.retryable = retryable


class UpdateDownloadCancelled(UpdateDownloadError):
    """``should_cancel`` returned True."""

    def __init__(self):
        super().__init__("Download cancelled", user_message="Cancelled")


# ============================================================================
# Helpers
# ============================================================================


def _sleep_within(seconds, deadline, should_cancel):
    """Sleep in slices so a cancel is noticed quickly. False = out of time."""
    end = min(time.monotonic() + seconds, deadline)
    while time.monotonic() < end:
        if should_cancel and should_cancel():
            raise UpdateDownloadCancelled()
        time.sleep(min(_BACKOFF_SLICE_S, max(0.0, end - time.monotonic())))
    return time.monotonic() < deadline


def _classify(exc):
    """Map a transport error to (message, retryable)."""
    if isinstance(exc, urllib.error.HTTPError):
        # A 4xx will not start working: the release row points at a key
        # that is missing, forbidden or expired. Retrying just delays the
        # browser fallback.
        return f"HTTP {exc.code}", 500 <= exc.code < 600
    return str(exc) or exc.__class__.__name__, True


def _open(url, offset, deadline):
    """Open *url*, optionally from *offset*. Returns (response, resumed)."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise UpdateDownloadError("Download deadline exceeded", retryable=False)

    request = urllib.request.Request(url)
    if offset:
        request.add_header("Range", f"bytes={offset}-")

    timeout = min(DOWNLOAD_SOCKET_TIMEOUT_S, remaining)
    response = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310
    # 206 means our range was honoured; anything else replays from zero
    # even though we asked not to, so the caller must reset.
    return response, bool(offset) and response.getcode() == 206


def _expected_total(response, offset, resumed):
    """Total size of the finished file, or 0 when the host didn't say."""
    length = response.headers.get("Content-Length")
    try:
        length = int(length)
    except (TypeError, ValueError):
        return 0
    return length + offset if resumed else length


def _open_part(part_path, offset):
    """Open the partial file positioned at *offset*, truncating any tail.

    The digest is the authority on how much of the file is trustworthy, not
    the size on disk: a write that failed mid-chunk can leave bytes the
    digest never saw, and appending after those would corrupt a download
    that then passes Content-Length and fails only at the checksum.
    """
    if not offset:
        return open(part_path, "wb"), 0
    try:
        handle = open(part_path, "r+b")
    except OSError:
        return open(part_path, "wb"), 0
    handle.seek(offset)
    handle.truncate(offset)
    return handle, offset


def _attempt(url, part_path, digest, offset, deadline, ctx):
    """One transfer attempt. Returns (bytes_written, digest)."""
    response, resumed = _open(url, offset, deadline)

    if offset and not resumed:
        logger.info("Server ignored Range — restarting update download")
        offset = 0
        digest = hashlib.sha256()

    total = _expected_total(response, offset, resumed)
    out, written = _open_part(part_path, offset if resumed else 0)
    ctx.verified = written
    last_report = 0.0

    try:
        while True:
            if ctx.should_cancel and ctx.should_cancel():
                raise UpdateDownloadCancelled()
            if time.monotonic() > deadline:
                raise UpdateDownloadError(
                    f"Download deadline exceeded after {written} bytes",
                    user_message="Download timed out",
                    retryable=False,
                )
            chunk = response.read(DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            written += len(chunk)
            ctx.verified = written

            now = time.monotonic()
            if ctx.on_progress and now - last_report >= DOWNLOAD_PROGRESS_INTERVAL_S:
                last_report = now
                ctx.on_progress(written, total)
    finally:
        for closeable in (out, response):
            try:
                closeable.close()
            except Exception:  # noqa: BLE001 - closing a dead handle
                pass

    if total and written != total:
        # A connection that closed early leaves a plausible-looking file.
        raise UpdateDownloadError(
            f"Truncated download: {written} of {total} bytes",
            user_message="Download interrupted",
            retryable=True,
        )
    if ctx.on_progress:
        ctx.on_progress(written, total or written)
    return written, digest


class _Ctx:
    """Callback bundle passed down to the attempt loop."""

    __slots__ = ("on_progress", "should_cancel", "verified")

    def __init__(self, on_progress, should_cancel):
        self.on_progress = on_progress
        self.should_cancel = should_cancel
        # Bytes the running digest has actually consumed — the only safe
        # offset to resume from.
        self.verified = 0


# ============================================================================
# Public API
# ============================================================================


def download_installer(
    url,
    final_path,
    expected_sha256,
    *,
    on_progress=None,
    should_cancel=None,
    deadline_s=None,
):
    """Download *url* to *final_path*, verifying *expected_sha256*.

    Safe to call from a background thread.  Writes to ``<final_path>.part``
    and renames only once the digest matches.

    Args:
        expected_sha256: hex digest from the backend.  Required — an
            unverified installer is never staged.
        on_progress: ``fn(transferred, total)`` on the calling thread.
        should_cancel: ``fn() -> bool``, polled between chunks.

    Returns:
        *final_path*.

    Raises:
        UpdateDownloadCancelled, UpdateDownloadError.
    """
    if not expected_sha256:
        raise UpdateDownloadError(
            "Release published without a sha256 — refusing to stage installer",
            user_message="Update could not be verified",
        )

    part_path = final_path + PARTIAL_SUFFIX
    ctx = _Ctx(on_progress, should_cancel)
    deadline = time.monotonic() + (deadline_s or DOWNLOAD_TOTAL_DEADLINE_S)
    backoff = DOWNLOAD_RETRY_BACKOFF_S
    digest = hashlib.sha256()
    offset = 0
    last_error = None

    try:
        for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
            try:
                written, digest = _attempt(
                    url, part_path, digest, offset, deadline, ctx,
                )
                actual = digest.hexdigest()
                if actual.lower() != expected_sha256.lower():
                    # Not retryable: a mismatch means the bytes we were
                    # served are not the release the backend signed off.
                    raise UpdateDownloadError(
                        f"Checksum mismatch (got {actual})",
                        user_message="Update failed verification",
                        retryable=False,
                    )
                os.replace(part_path, final_path)
                logger.info(
                    "Update installer staged: %s (%d bytes)", final_path, written,
                )
                return final_path

            except UpdateDownloadCancelled:
                raise
            except UpdateDownloadError as e:
                last_error = e
                if not e.retryable or attempt >= DOWNLOAD_MAX_ATTEMPTS:
                    break
            except Exception as e:  # noqa: BLE001 - transport layer
                message, retryable = _classify(e)
                last_error = UpdateDownloadError(
                    f"Installer download failed: {message}",
                    # The classifier's message is transport-level ("HTTP 404",
                    # an errno) — never the presigned URL — and it is exactly
                    # what a tester needs to see on the toast.
                    user_message=f"Download failed ({message[:60]})",
                    retryable=retryable,
                )
                if not retryable or attempt >= DOWNLOAD_MAX_ATTEMPTS:
                    break

            logger.warning(
                "Update download attempt %d/%d failed, retrying: %s",
                attempt, DOWNLOAD_MAX_ATTEMPTS, last_error,
            )
            offset = ctx.verified
            if not _sleep_within(backoff, deadline, should_cancel):
                break
            backoff *= DOWNLOAD_RETRY_BACKOFF_FACTOR

    except BaseException:
        _discard(part_path)
        raise

    _discard(part_path)
    raise last_error or UpdateDownloadError("Installer download failed")


def _discard(path):
    try:
        os.remove(path)
    except OSError:
        pass
