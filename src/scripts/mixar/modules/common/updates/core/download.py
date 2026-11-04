# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Installer Download

Streams the release installer into the staging directory, verifying it
against the ``sha256`` the backend published before the file is given its
final name. The transfer itself is the shared
``common/remote_assets/core/download.py`` (checksum-gated rename, Range
resume from the verified bytes, bounded total deadline); this module keeps
the updater's budget, its exception names and its logging wording so the
install flow and its tests are unchanged.

Imports no ``bpy`` — every callback fires on the download thread and callers
must marshal to the main thread themselves.
"""

import urllib.error
import urllib.request  # noqa: F401 - tests patch ``download.urllib.request.urlopen``

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_
from mixar.modules.common.remote_assets.core import download as _shared

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


class UpdateDownloadError(_shared.DownloadError):
    """A download or verification failure. ``user_message`` is UI-safe."""

    def __init__(self, message, user_message="", retryable=False):
        super().__init__(message, user_message or n_("Download failed"), retryable)


class UpdateDownloadCancelled(UpdateDownloadError):
    """``should_cancel`` returned True."""

    def __init__(self):
        super().__init__("Download cancelled", user_message=n_("Cancelled"))


def _classify(exc):
    """Map a transport error to (message, retryable)."""
    return _shared.classify(exc)


def _policy():
    # Read at call time: tests lower ``DOWNLOAD_RETRY_BACKOFF_S`` on this
    # module to keep the retry path fast.
    return _shared.Policy(
        total_deadline_s=DOWNLOAD_TOTAL_DEADLINE_S,
        socket_timeout_s=DOWNLOAD_SOCKET_TIMEOUT_S,
        chunk_bytes=DOWNLOAD_CHUNK_BYTES,
        max_attempts=DOWNLOAD_MAX_ATTEMPTS,
        retry_backoff_s=globals()["DOWNLOAD_RETRY_BACKOFF_S"],
        retry_backoff_factor=DOWNLOAD_RETRY_BACKOFF_FACTOR,
        progress_interval_s=DOWNLOAD_PROGRESS_INTERVAL_S,
        partial_suffix=PARTIAL_SUFFIX,
        error_cls=UpdateDownloadError,
        cancelled_cls=UpdateDownloadCancelled,
        what="installer",
    )


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

    Safe to call from a background thread. Writes to ``<final_path>.part``
    and renames only once the digest matches; the partial file is removed
    on failure (an installer is never resumed across sessions).

    Raises ``UpdateDownloadCancelled`` / ``UpdateDownloadError``.
    """
    if not expected_sha256:
        raise UpdateDownloadError(
            "Release published without a sha256 — refusing to stage installer",
            user_message=n_("Update could not be verified"),
        )
    return _shared.download_file(
        url, final_path, expected_sha256,
        on_progress=on_progress, should_cancel=should_cancel,
        deadline_s=deadline_s, policy=_policy(),
    )
