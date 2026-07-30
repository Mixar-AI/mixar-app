# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded, verified, retryable result-file download.

Split out of ``model_io`` because the transfer needs real policy rather
than a read loop. Three production defects motivated each piece:

- ``urlopen(timeout=...)`` is a *per-read* socket timeout, so a trickling
  transfer reset it forever and a finished job sat in "Downloading…" for
  10+ minutes holding a concurrency slot. Hence a total deadline enforced
  between chunks (:data:`DOWNLOAD_TOTAL_DEADLINE_S`).
- The read loop stopped at EOF and returned the path, so a connection that
  closed early produced a partial ``.glb`` that was then imported. Hence
  the ``Content-Length`` check.
- A transient failure permanently failed a job whose result URL was still
  valid. Hence bounded retries — but never for a 4xx, because these are
  presigned S3 URLs and an expired one will not start working.

Runs on the queue's background download thread: imports no ``bpy`` and
touches no Blender state. ``on_progress`` and ``should_cancel`` are invoked
on that same thread, so callers must only read/write plain values in them.
"""

import http.client
import os
import socket
import tempfile
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
    LOG_PREFIX,
)

logger = get_logger(__name__)

_EXT_MAP = {"GLB": ".glb", "OBJ": ".obj", "FBX": ".fbx"}

# Sleep slice while backing off, so a cancel is noticed within ~250 ms
# instead of at the end of the backoff.
_BACKOFF_SLICE_S = 0.25


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DownloadError(Exception):
    """A result download failed.

    ``user_message`` is the UI-safe string (never contains the presigned
    URL — its signature reads as a token and would be scrubbed away by
    ``sanitize_message``, blanking the queue row). ``retryable`` marks
    failures worth another attempt against the same URL.
    """

    def __init__(self, message, user_message="", retryable=False):
        super().__init__(message)
        self.user_message = user_message
        self.retryable = retryable


class DownloadCancelled(DownloadError):
    """``should_cancel`` returned True — the caller cancelled the job."""

    def __init__(self, message="Download cancelled"):
        super().__init__(message, user_message="Cancelled")


def _remove(filepath):
    try:
        os.remove(filepath)
    except OSError:
        pass


def _classify_http_error(exc):
    """Map an HTTPError to a DownloadError, deciding retryability."""
    code = getattr(exc, "code", 0) or 0
    if code in (408, 429) or code >= 500:
        return DownloadError(
            f"Result host returned HTTP {code}",
            "Download failed — please retry",
            retryable=True,
        )
    if code == 403:
        # Presigned S3 URLs expire. We must not re-derive or refresh one
        # client-side, and retrying a 403 just spins, so stop and say so.
        return DownloadError(
            f"Result link is no longer valid (HTTP {code}, presigned URL expired)",
            "Download link expired — please run the generation again",
        )
    if code == 404:
        return DownloadError(
            f"Result file is no longer available (HTTP {code})",
            "Result is no longer available — please run the generation again",
        )
    return DownloadError(
        f"Result host returned HTTP {code}",
        "Download failed — please retry",
    )


def _deadline_error(written, total):
    if total:
        detail = f"{written} of {total} bytes transferred"
    else:
        detail = f"{written} bytes transferred"
    return DownloadError(
        f"Download exceeded its total time limit ({detail})",
        "Download timed out — please retry",
    )


def _content_length(response):
    """``Content-Length`` as an int, or 0 when absent/unusable.

    0 means "not verifiable": we then keep the original read-until-EOF
    behaviour and make no completeness claim.
    """
    try:
        raw = response.headers.get("Content-Length")
    except Exception:
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _sleep_within(seconds, deadline, should_cancel):
    """Back off in cancel-aware slices. False if the deadline can't afford it."""
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


# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------


def _open(url, deadline):
    """Open the URL, capping the socket timeout by the remaining budget."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _deadline_error(0, 0)
    # Capping matters: an uncapped 120 s read on a wedged socket would
    # otherwise overshoot the total deadline by a whole socket timeout.
    timeout = min(DOWNLOAD_SOCKET_TIMEOUT_S, remaining)
    try:
        return urllib.request.urlopen(url, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            e.close()
        except Exception:
            pass
        raise _classify_http_error(e) from e
    except urllib.error.URLError as e:
        raise DownloadError(
            f"Could not reach the result host: {e.reason}",
            "Could not download the result — check your internet connection",
            retryable=True,
        ) from e
    except (TimeoutError, socket.timeout, http.client.HTTPException, OSError) as e:
        raise DownloadError(
            f"Connection to the result host failed: {e}",
            "Could not download the result — check your internet connection",
            retryable=True,
        ) from e


def _attempt(url, filepath, deadline, attempt, on_progress, should_cancel):
    """One full transfer into *filepath*. Raises DownloadError on any failure."""
    response = _open(url, deadline)
    total = _content_length(response)
    written = 0
    # Seeded with "now" rather than 0 so the throttle starts counting from the
    # transfer, instead of the first chunk always beating it.
    last_report = time.monotonic()

    if on_progress is not None:
        on_progress(0, total, attempt)

    try:
        with open(filepath, "wb") as out:
            while True:
                # Cancel and deadline are both checked per chunk so each
                # takes effect promptly instead of after the transfer.
                if should_cancel is not None and should_cancel():
                    raise DownloadCancelled()
                if time.monotonic() >= deadline:
                    raise _deadline_error(written, total)
                try:
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                except (TimeoutError, socket.timeout) as e:
                    raise DownloadError(
                        f"Result host stopped responding after {written} bytes: {e}",
                        "Download stalled — please retry",
                        retryable=True,
                    ) from e
                except (http.client.HTTPException, OSError) as e:
                    raise DownloadError(
                        f"Connection dropped after {written} bytes: {e}",
                        "Download failed — please retry",
                        retryable=True,
                    ) from e
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
                now = time.monotonic()
                if (
                    on_progress is not None
                    and now - last_report >= DOWNLOAD_PROGRESS_INTERVAL_S
                ):
                    last_report = now
                    on_progress(written, total, attempt)
    finally:
        try:
            response.close()
        except Exception:
            pass

    if total and written != total:
        # A short body used to be imported as a valid partial GLB, surfacing
        # as a confusing glTF parse error (or worse, a partial "success").
        raise DownloadError(
            f"Download incomplete: received {written} of {total} bytes",
            "Download was incomplete — please retry",
            retryable=True,
        )

    if on_progress is not None:
        on_progress(written, total or written, attempt)
    return written


def download_file(
    url,
    file_type="GLB",
    *,
    on_progress=None,
    should_cancel=None,
    deadline_s=None,
):
    """Download *url* to a temp file. Safe to call from a background thread.

    Bounded by a total deadline shared across every retry attempt, verified
    against ``Content-Length`` when the host sends one, and abortable via
    *should_cancel*. The temp file is removed on every failure path, so a
    failed transfer never leaks a multi-MB file into tempdir.

    Args:
        on_progress: ``fn(transferred, total, attempt)``, called on the
            calling (background) thread at most every
            ``DOWNLOAD_PROGRESS_INTERVAL_S``. ``total`` is 0 when the host
            sent no ``Content-Length``. Must not touch bpy or the UI.
        should_cancel: ``fn() -> bool``, polled between chunks.
        deadline_s: total budget override (tests); defaults to
            ``DOWNLOAD_TOTAL_DEADLINE_S``.

    Returns:
        The path to the downloaded temp file.

    Raises:
        DownloadCancelled: *should_cancel* returned True.
        DownloadError: everything else. ``.user_message`` is UI-safe.
    """
    ext = _EXT_MAP.get(file_type.upper(), ".glb")
    fd, filepath = tempfile.mkstemp(suffix=ext, prefix="mixar_result_")
    os.close(fd)

    budget = DOWNLOAD_TOTAL_DEADLINE_S if deadline_s is None else deadline_s
    deadline = time.monotonic() + budget
    backoff = DOWNLOAD_RETRY_BACKOFF_S
    last_error = None

    try:
        for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
            try:
                _attempt(
                    url, filepath, deadline, attempt, on_progress, should_cancel,
                )
                return filepath
            except DownloadCancelled:
                raise
            except DownloadError as e:
                last_error = e
                if not e.retryable or attempt >= DOWNLOAD_MAX_ATTEMPTS:
                    break
                logger.warning(
                    "%s download attempt %d/%d failed, retrying: %s",
                    LOG_PREFIX, attempt, DOWNLOAD_MAX_ATTEMPTS, e,
                )
                if not _sleep_within(backoff, deadline, should_cancel):
                    # No room left in the deadline — retrying would only
                    # burn budget we no longer have.
                    break
                backoff *= DOWNLOAD_RETRY_BACKOFF_FACTOR
    except BaseException:
        _remove(filepath)
        raise

    _remove(filepath)
    raise last_error or DownloadError(
        "Download failed", "Download failed — please retry",
    )
