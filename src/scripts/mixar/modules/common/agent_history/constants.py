# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local archival wire and disk bounds (no SQLite)."""
CAPABILITY = 'agent_history_v1'
POLL_SECONDS = 2.0
REQUEST_TIMEOUT = 20.0
SEGMENT_BYTES = 8 * 1024 * 1024
MAX_RECORD_BYTES = 12 * 1024 * 1024
MAX_READ_CHARS = 12000
MAX_READ_RECORDS = 20
MAX_BLOB_BYTES = 8 * 1024 * 1024
