# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local archival wire and disk bounds (no SQLite)."""
CAPABILITY = 'agent_history_v1'
# v2: image bytes leave the socket; agent.history_sync sends {"blobs": "reference"}
# and the archive thread fetches GET /agent/history/blob over HTTP.
CAPABILITY_V2 = 'agent_history_v2'
POLL_SECONDS = 2.0
REQUEST_TIMEOUT = 20.0  # main-thread scene capture only
# A sync reply is bound to its connection: wait for it (or the disconnect) instead
# of abandoning it on a timer and re-requesting the same batch. The cap only
# guards against a server that keeps the socket open and never answers.
REPLY_WAIT_SECONDS = 600.0
BLOB_FETCH_TIMEOUT = 300.0
BACKOFF_MAX_SECONDS = 60.0  # poll interval cap after consecutive failures
SEGMENT_BYTES = 8 * 1024 * 1024
MAX_RECORD_BYTES = 12 * 1024 * 1024
MAX_READ_CHARS = 12000
MAX_READ_RECORDS = 20
MAX_BLOB_BYTES = 8 * 1024 * 1024
