# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Defaults for ``remote_assets.core.download``. Callers with their own
budget (the updater's hour-long installer, a 3 MB tour part) pass a
``Policy``; these are the values a plain ``download_file`` call gets."""

TOTAL_DEADLINE_S = 600.0
SOCKET_TIMEOUT_S = 60.0
CHUNK_BYTES = 256 * 1024
MAX_ATTEMPTS = 3
RETRY_BACKOFF_S = 2.0
RETRY_BACKOFF_FACTOR = 3.0
PROGRESS_INTERVAL_S = 0.5
PARTIAL_SUFFIX = ".part"
