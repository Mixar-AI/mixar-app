# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Verified streaming download.

Streams a URL into ``<final_path>.part`` and gives the file its final name
only once its sha256 matches the digest the caller was promised. Imports no
``bpy`` — every callback fires on the download thread and callers marshal
to the main thread themselves. Grown out of the self-updater's installer
download and shared with the onboarding tour's language packs.

Three properties matter here and each is deliberate:

- **The checksum gates the filename.** A finished file is never a
  truncated or tampered one; the updater runs it elevated and the tour
  plays it as narration.
- **Transfers resume.** A retry sends a ``Range`` header from the bytes
  the running digest has consumed. With ``resume_existing=True`` a
  ``.part`` left by an earlier process is hashed and continued too (a 20 MB
  language pack on a flaky connection), and the partial file is kept on
  failure so the next launch picks it up. A server that ignores the range
  and replays the whole body is handled by resetting both file and digest.
- **The budget is bounded.** ``urlopen(timeout=...)`` is a per-read
  timeout that a trickling connection resets forever, so a total deadline
  is enforced between chunks.
"""

import hashlib
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from mixar.config.logging_config import get_logger

from .. import constants as C

logger = get_logger(__name__)

_BACKOFF_SLICE_S = 0.25


class DownloadError(Exception):
    """A download or verification failure. ``user_message`` is UI-safe."""

    def __init__(self, message, user_message="", retryable=False):
        super().__init__(message)
        self.user_message = user_message or "Download failed"
        self.retryable = retryable


class DownloadCancelled(DownloadError):
    """``should_cancel`` returned True."""

    def __init__(self):
        super().__init__("Download cancelled", user_message="Cancelled")


@dataclass(frozen=True)
class Policy:
    total_deadline_s: float = C.TOTAL_DEADLINE_S
    socket_timeout_s: float = C.SOCKET_TIMEOUT_S
    chunk_bytes: int = C.CHUNK_BYTES
    max_attempts: int = C.MAX_ATTEMPTS
    retry_backoff_s: float = C.RETRY_BACKOFF_S
    retry_backoff_factor: float = C.RETRY_BACKOFF_FACTOR
    progress_interval_s: float = C.PROGRESS_INTERVAL_S
    partial_suffix: str = C.PARTIAL_SUFFIX
    # Errors are subclasses the caller wants raised (the updater keeps its
    # own exception names so its callers and tests are untouched).
    error_cls: type = DownloadError
    cancelled_cls: type = DownloadCancelled
    what: str = "file"          # log/user wording: "installer", "tour part"


# ============================================================================
# Helpers
# ============================================================================


def _sleep_within(seconds, deadline, should_cancel, policy):
    """Sleep in slices so a cancel is noticed quickly. False = out of time."""
    end = min(time.monotonic() + seconds, deadline)
    while time.monotonic() < end:
        if should_cancel and should_cancel():
            raise policy.cancelled_cls()
        time.sleep(min(_BACKOFF_SLICE_S, max(0.0, end - time.monotonic())))
    return time.monotonic() < deadline


def classify(exc):
    """Map a transport error to (message, retryable)."""
    if isinstance(exc, urllib.error.HTTPError):
        # A 4xx will not start working: the URL points at a key that is
        # missing, forbidden or expired.
        return f"HTTP {exc.code}", 500 <= exc.code < 600
    return str(exc) or exc.__class__.__name__, True


def _open(url, offset, deadline, policy):
    """Open *url*, optionally from *offset*. Returns (response, resumed)."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise policy.error_cls("Download deadline exceeded", retryable=False)

    request = urllib.request.Request(url)
    if offset:
        request.add_header("Range", f"bytes={offset}-")

    timeout = min(policy.socket_timeout_s, remaining)
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


def _hash_existing(part_path, chunk_bytes):
    """(digest, size) of a ``.part`` left by an earlier process."""
    digest = hashlib.sha256()
    size = 0
    try:
        with open(part_path, "rb") as fh:
            while True:
                chunk = fh.read(chunk_bytes)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        return hashlib.sha256(), 0
    return digest, size


def _attempt(url, part_path, digest, offset, deadline, ctx, policy):
    """One transfer attempt. Returns (bytes_written, digest)."""
    response, resumed = _open(url, offset, deadline, policy)

    if offset and not resumed:
        logger.info("Server ignored Range — restarting %s download", policy.what)
        offset = 0
        digest = hashlib.sha256()

    total = _expected_total(response, offset, resumed)
    out, written = _open_part(part_path, offset if resumed else 0)
    ctx.verified = written
    last_report = 0.0

    try:
        while True:
            if ctx.should_cancel and ctx.should_cancel():
                raise policy.cancelled_cls()
            if time.monotonic() > deadline:
                raise policy.error_cls(
                    f"Download deadline exceeded after {written} bytes",
                    user_message="Download timed out",
                    retryable=False,
                )
            chunk = response.read(policy.chunk_bytes)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            written += len(chunk)
            ctx.verified = written

            now = time.monotonic()
            if ctx.on_progress and now - last_report >= policy.progress_interval_s:
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
        raise policy.error_cls(
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


def download_file(
    url,
    final_path,
    expected_sha256,
    *,
    on_progress=None,
    should_cancel=None,
    deadline_s=None,
    policy=None,
    resume_existing=False,
    keep_partial=False,
):
    """Download *url* to *final_path*, verifying *expected_sha256*.

    Safe to call from a background thread. Writes to ``<final_path>.part``
    and renames only once the digest matches.

    Args:
        expected_sha256: hex digest the publisher recorded. Required.
        on_progress: ``fn(transferred, total)`` on the calling thread.
        should_cancel: ``fn() -> bool``, polled between chunks.
        deadline_s: total budget; defaults to the policy's.
        policy: a ``Policy``; defaults are ``remote_assets.constants``.
        resume_existing: hash a ``.part`` left by an earlier process and
            continue from it instead of starting over.
        keep_partial: leave the ``.part`` in place on failure (never on a
            checksum mismatch or a cancel) so a later call can resume.

    Returns *final_path*. Raises ``policy.cancelled_cls`` /
    ``policy.error_cls`` (``DownloadCancelled`` / ``DownloadError``).
    """
    policy = policy or Policy()
    if not expected_sha256:
        raise policy.error_cls(
            f"No sha256 published for this {policy.what} — refusing to download",
            user_message="Download could not be verified",
        )

    part_path = final_path + policy.partial_suffix
    ctx = _Ctx(on_progress, should_cancel)
    deadline = time.monotonic() + (deadline_s or policy.total_deadline_s)
    backoff = policy.retry_backoff_s
    digest = hashlib.sha256()
    offset = 0
    if resume_existing and os.path.isfile(part_path):
        digest, offset = _hash_existing(part_path, policy.chunk_bytes)
        if offset:
            logger.info("Resuming %s download from %d bytes", policy.what, offset)
    last_error = None
    discard = True

    try:
        for attempt in range(1, policy.max_attempts + 1):
            try:
                written, digest = _attempt(
                    url, part_path, digest, offset, deadline, ctx, policy,
                )
                actual = digest.hexdigest()
                if actual.lower() != expected_sha256.lower():
                    # Not retryable: a mismatch means the bytes we were
                    # served are not the file the publisher signed off.
                    raise policy.error_cls(
                        f"Checksum mismatch (got {actual})",
                        user_message="Download failed verification",
                        retryable=False,
                    )
                os.replace(part_path, final_path)
                logger.info("%s downloaded: %s (%d bytes)",
                            policy.what.capitalize(), final_path, written)
                return final_path

            except policy.cancelled_cls:
                raise
            except policy.error_cls as e:
                last_error = e
                if not e.retryable or attempt >= policy.max_attempts:
                    break
            except Exception as e:  # noqa: BLE001 - transport layer
                message, retryable = classify(e)
                last_error = policy.error_cls(
                    f"{policy.what.capitalize()} download failed: {message}",
                    # The classifier's message is transport-level ("HTTP
                    # 404", an errno) — never the URL.
                    user_message=f"Download failed ({message[:60]})",
                    retryable=retryable,
                )
                if not retryable or attempt >= policy.max_attempts:
                    break

            logger.warning(
                "%s download attempt %d/%d failed, retrying: %s",
                policy.what.capitalize(), attempt, policy.max_attempts, last_error,
            )
            offset = ctx.verified
            if not _sleep_within(backoff, deadline, should_cancel, policy):
                break
            backoff *= policy.retry_backoff_factor

        # A failed transfer (not a bad checksum) may leave its bytes for a
        # later resume when the caller asked for that.
        if keep_partial and last_error is not None and last_error.retryable:
            discard = False
    except BaseException:
        _discard(part_path)
        raise

    if discard:
        _discard(part_path)
    raise last_error or policy.error_cls(f"{policy.what.capitalize()} download failed")


def _discard(path):
    try:
        os.remove(path)
    except OSError:
        pass
