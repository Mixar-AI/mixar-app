# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Content-free update failure diagnostics; never send exception text or paths."""

import errno
import socket
import urllib.error


def failure_details(error, stage):
    """Never raises: the worker calls it before the "download finished" UI step."""
    try:
        return _classify(error, stage)
    except Exception:  # noqa: BLE001 - diagnostics must never break the UI step
        return {'reason_code': 'unexpected_error', 'error_detail': 'unclassified', 'stage': stage}


def _classify(error, stage):
    stage = getattr(error, 'stage', '') or stage
    cause = error.__cause__ or error
    network = isinstance(cause, urllib.error.URLError)
    if isinstance(cause, urllib.error.URLError) and isinstance(cause.reason, Exception):
        cause = cause.reason
    code = getattr(error, 'reason_code', '')
    number = getattr(cause, 'errno', None)
    if not code:
        if isinstance(cause, urllib.error.HTTPError):
            code = 'http_error'
        elif number == errno.ENOSPC:
            code = 'disk_full'
        elif number == errno.EROFS:
            code = 'read_only'
        elif isinstance(cause, PermissionError) or number in (errno.EACCES, errno.EPERM):
            code = 'permission_denied'
        elif isinstance(cause, (TimeoutError, socket.timeout)):
            code = 'timeout'
        elif network or isinstance(cause, (ConnectionError, socket.gaierror)):
            code = 'network_error'
        elif isinstance(cause, OSError):
            code = 'filesystem_error'
        else:
            code = 'unexpected_error'
    # Fixed diagnostic values only: raw errors may contain signed URLs,
    # proxy credentials, usernames, local paths or signature-tool output.
    detail = type(cause).__name__
    if isinstance(cause, urllib.error.HTTPError):
        detail += f': HTTP {cause.code}'
    elif isinstance(number, int):
        detail += f': errno {number}'
    return {'reason_code': code, 'error_detail': detail, 'stage': stage}


def capture_download_outcome(version, outcome, details):
    """Emit the worker's snapshot on the main thread, even after a UI error."""
    try:
        from ...analytics.update_events import capture_update_download

        capture_update_download(version, outcome, details=details)
    except Exception:  # noqa: BLE001 - telemetry is fail-open
        pass
