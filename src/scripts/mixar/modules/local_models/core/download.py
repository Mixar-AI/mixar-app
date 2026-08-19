# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Verified, resumable, bounded download for multi-GB runtime/model files.

Policy skeleton copied from the job-queue result downloader
(``modules/common/job_queue/core/downloader.py``): per-read socket timeout
capped by the remaining total budget, one total deadline shared across all
retries, Content-Length verification, never retry a 4xx, and cancel polled
between chunks and inside backoff slices. On top of that, this downloader:

- writes to ``dest_path + ".part"`` and ``os.replace``s into place only
  after every check passed, so a partial file can never be mistaken for a
  finished one;
- rolls SHA-256 in the chunk loop and treats a digest mismatch as a
  terminal failure that deletes the ``.part``;
- resumes an existing ``.part`` with a ``Range`` request, re-hashing the
  existing prefix first so the final digest still covers every byte on
  disk (a server that ignores ``Range`` and answers 200 restarts the
  transfer from scratch, transparently);
- scales the default deadline by the expected size, because a 17 GB GGUF
  cannot fit in the job queue's 600 s budget.

A cancel or a retryable failure keeps the ``.part`` on disk so the next
call resumes instead of restarting.

No bpy imports — safe to call from any background thread. ``on_progress``
and ``should_cancel`` run on the calling thread and must not touch bpy.
"""

import hashlib
import http.client
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from mixar.config.logging_config import get_logger

from ..constants import (
    DOWNLOAD_CHUNK_BYTES,
    DOWNLOAD_DEADLINE_BYTES_PER_S,
    DOWNLOAD_MAX_ATTEMPTS,
    DOWNLOAD_MIN_DEADLINE_S,
    DOWNLOAD_PROGRESS_INTERVAL_S,
    DOWNLOAD_RETRY_BACKOFF_FACTOR,
    DOWNLOAD_RETRY_BACKOFF_S,
    DOWNLOAD_SOCKET_TIMEOUT_S,
    LOG_PREFIX,
)

logger = get_logger(__name__)

_BACKOFF_SLICE_S = 0.25

# Test seam: unit tests monkeypatch this with a fake opener.
_urlopen = urllib.request.urlopen


class DownloadError(Exception):
    """A download failed. ``user_message`` is UI-safe (never the URL)."""

    def __init__(self, message, user_message="", retryable=False):
        super().__init__(message)
        self.user_message = user_message or "Download failed — please retry"
        self.retryable = retryable


class DownloadCancelled(DownloadError):
    """``should_cancel`` returned True."""

    def __init__(self, message="Download cancelled"):
        super().__init__(message, user_message="Cancelled")


def default_deadline_s(expected_size):
    """Total budget scaled so a 200 KiB/s link can still finish."""
    scaled = (expected_size or 0) // DOWNLOAD_DEADLINE_BYTES_PER_S
    return max(DOWNLOAD_MIN_DEADLINE_S, scaled)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _deadline_error(transferred, total):
    detail = (
        f"{transferred} of {total} bytes" if total else f"{transferred} bytes"
    )
    return DownloadError(
        f"Download exceeded its total time limit ({detail} transferred)",
        "Download timed out — please retry",
    )


def _classify_http_error(exc):
    code = getattr(exc, "code", 0) or 0
    if code in (408, 429) or code >= 500:
        return DownloadError(
            f"Download host returned HTTP {code}", retryable=True
        )
    return DownloadError(
        f"Download host returned HTTP {code}",
        "Download failed — the file is not available",
    )


def _sleep_within(seconds, deadline, should_cancel):
    """Cancel-aware backoff. False if the deadline can't afford it."""
    if time.monotonic() + seconds >= deadline:
        return False
    end = time.monotonic() + seconds
    while True:
        if should_cancel is not None and should_cancel():
            raise DownloadCancelled()
        remaining = end - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(_BACKOFF_SLICE_S, remaining))


def _content_length(response):
    try:
        value = int(response.headers.get("Content-Length"))
    except (TypeError, ValueError, AttributeError):
        return 0
    return value if value > 0 else 0


def _open(url, offset, deadline):
    """Open *url* (with a Range header past *offset*), budget-capped."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _deadline_error(offset, 0)
    timeout = min(DOWNLOAD_SOCKET_TIMEOUT_S, remaining)
    headers = {}
    if offset > 0:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        return _urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            e.close()
        except Exception:
            pass
        if e.code == 416 and offset > 0:
            # Our .part no longer matches the remote file — restart clean.
            raise _StaleResume() from e
        raise _classify_http_error(e) from e
    except urllib.error.URLError as e:
        raise DownloadError(
            f"Could not reach the download host: {e.reason}",
            "Could not download — check your internet connection",
            retryable=True,
        ) from e
    except (TimeoutError, socket.timeout, http.client.HTTPException, OSError) as e:
        raise DownloadError(
            f"Connection to the download host failed: {e}",
            "Could not download — check your internet connection",
            retryable=True,
        ) from e


class _StaleResume(Exception):
    """The server rejected our resume offset (HTTP 416)."""


def _rehash_prefix(part_path, hasher, deadline, should_cancel):
    """Roll the existing .part bytes into *hasher*. Returns byte count."""
    size = 0
    with open(part_path, "rb") as existing:
        while True:
            if should_cancel is not None and should_cancel():
                raise DownloadCancelled()
            if time.monotonic() >= deadline:
                raise _deadline_error(size, 0)
            chunk = existing.read(DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                return size
            hasher.update(chunk)
            size += len(chunk)


def _attempt(url, part_path, state, deadline, attempt, expected_size,
             on_progress, should_cancel):
    """One transfer (append past ``state['offset']``) into the .part file."""
    response = _open(url, state["offset"], deadline)
    try:
        status = response.status if hasattr(response, "status") else response.getcode()
        if state["offset"] > 0 and status != 206:
            # Server ignored the Range request: restart from scratch.
            state["offset"] = 0
            state["hasher"] = hashlib.sha256()
        content_length = _content_length(response)
        total = expected_size or (
            state["offset"] + content_length if content_length else 0
        )
        written = 0
        last_report = time.monotonic()
        if on_progress is not None:
            on_progress(state["offset"], total, attempt)

        mode = "ab" if state["offset"] > 0 else "wb"
        with open(part_path, mode) as out:
            while True:
                if should_cancel is not None and should_cancel():
                    raise DownloadCancelled()
                if time.monotonic() >= deadline:
                    raise _deadline_error(state["offset"] + written, total)
                try:
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                except (TimeoutError, socket.timeout) as e:
                    # Keep what we got — the in-process retry (and any later
                    # cross-call resume) must Range past these bytes, and the
                    # hasher has already consumed them.
                    state["offset"] += written
                    raise DownloadError(
                        f"Host stopped responding after {written} bytes: {e}",
                        "Download stalled — please retry",
                        retryable=True,
                    ) from e
                except (http.client.HTTPException, OSError) as e:
                    state["offset"] += written  # keep what we got (see above)
                    raise DownloadError(
                        f"Connection dropped after {written} bytes: {e}",
                        retryable=True,
                    ) from e
                if not chunk:
                    break
                out.write(chunk)
                state["hasher"].update(chunk)
                written += len(chunk)
                now = time.monotonic()
                if (
                    on_progress is not None
                    and now - last_report >= DOWNLOAD_PROGRESS_INTERVAL_S
                ):
                    last_report = now
                    on_progress(state["offset"] + written, total, attempt)
    finally:
        try:
            response.close()
        except Exception:
            pass

    if content_length and written != content_length:
        state["offset"] += written  # keep what we got; retry resumes here
        raise DownloadError(
            f"Incomplete body: {written} of {content_length} bytes",
            "Download was incomplete — please retry",
            retryable=True,
        )
    state["offset"] += written
    if on_progress is not None:
        on_progress(state["offset"], total or state["offset"], attempt)


def download_file(url, dest_path, *, expected_sha256=None, expected_size=None,
                  on_progress=None, should_cancel=None, deadline_s=None):
    """Download *url* to *dest_path*, verified and resumable.

    Args:
        url: HTTPS URL (anything else is refused).
        dest_path: final location; the transfer streams to
            ``dest_path + ".part"`` and is renamed only after verification.
        expected_sha256: hex digest; mismatch is terminal and deletes the
            ``.part``.
        expected_size: exact byte size; drives the default deadline and the
            final size check.
        on_progress: ``fn(transferred, total, attempt)`` on the calling
            thread, throttled; ``total`` may be 0 (unknown).
        should_cancel: ``fn() -> bool`` polled between chunks and during
            backoff. Cancelling keeps the ``.part`` for a later resume.
        deadline_s: total budget override; defaults to
            ``default_deadline_s(expected_size)``.

    Returns:
        ``dest_path``.

    Raises:
        DownloadCancelled | DownloadError (``.user_message`` is UI-safe).
    """
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme != "https":
        raise DownloadError(
            f"Refusing non-https download URL (scheme={scheme!r})",
            "Download failed — invalid download source",
        )

    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    part_path = dest_path + ".part"

    budget = default_deadline_s(expected_size) if deadline_s is None else deadline_s
    deadline = time.monotonic() + budget
    state = {"offset": 0, "hasher": hashlib.sha256()}

    if os.path.exists(part_path):
        part_size = os.path.getsize(part_path)
        if expected_size and part_size >= expected_size:
            _remove(part_path)  # complete-or-overshot leftover: distrust it
        elif part_size > 0:
            state["offset"] = _rehash_prefix(
                part_path, state["hasher"], deadline, should_cancel
            )
            logger.info(
                "%s resuming %s from %d bytes", LOG_PREFIX,
                os.path.basename(dest_path), state["offset"],
            )

    backoff = DOWNLOAD_RETRY_BACKOFF_S
    last_error = None
    for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
        try:
            _attempt(
                url, part_path, state, deadline, attempt, expected_size,
                on_progress, should_cancel,
            )
            last_error = None
            break
        except _StaleResume:
            _remove(part_path)
            state["offset"] = 0
            state["hasher"] = hashlib.sha256()
            last_error = DownloadError(
                "Server rejected the resume offset", retryable=True
            )
        except DownloadCancelled:
            raise
        except DownloadError as e:
            last_error = e
            if not e.retryable or attempt >= DOWNLOAD_MAX_ATTEMPTS:
                raise
        logger.warning(
            "%s download attempt %d/%d failed, retrying: %s",
            LOG_PREFIX, attempt, DOWNLOAD_MAX_ATTEMPTS, last_error,
        )
        if not _sleep_within(backoff, deadline, should_cancel):
            raise last_error
        backoff *= DOWNLOAD_RETRY_BACKOFF_FACTOR
    if last_error is not None:
        raise last_error

    final_size = os.path.getsize(part_path)
    if expected_size and final_size != expected_size:
        _remove(part_path)
        raise DownloadError(
            f"Size mismatch: got {final_size}, expected {expected_size}",
            "Downloaded file failed verification — please retry",
        )
    if expected_sha256:
        digest = state["hasher"].hexdigest()
        if digest.lower() != expected_sha256.lower():
            _remove(part_path)
            raise DownloadError(
                f"SHA-256 mismatch: got {digest}, expected {expected_sha256}",
                "Downloaded file failed verification — please retry",
            )
    os.replace(part_path, dest_path)
    return dest_path
