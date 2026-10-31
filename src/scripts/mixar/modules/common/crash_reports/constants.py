# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Limits and names for crash reporting (docs/modules/crash-handling.md)."""

ENDPOINT = "api/v1/crash-reports"
REQUEST_TIMEOUT_S = 15.0

# <user config>/mixar/crash_reports/
STATE_SUBDIR = "crash_reports"
SENT_LEDGER = "sent.json"
PENDING_FILE = "pending.json"
SESSION_PREFIX = "session-"

# Crash files: Blender's handler writes <tempdir base>/mixar.crash.txt, or
# <blend name>.crash.txt when a file is open. macOS also keeps its own report.
CRASH_TXT_GLOB = "*.crash.txt"
# The background render worker (Mixar --background, spawned by the app) gets
# its own temp dir, so its crash log lands in
# <tmp>/mixar_render_worker/<app pid>/worker-<kind>/tmp/ (common/render_worker).
WORKER_CRASH_GLOB = ("mixar_render_worker", "*", "worker-*", "tmp", "*.crash.txt")
MACOS_REPORTS_DIR = "~/Library/Logs/DiagnosticReports"
MACOS_REPORT_GLOB = "Mixar*.ips"
MAX_FILE_AGE_DAYS = 30
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_REPORTS_PER_LAUNCH = 10
SENT_LEDGER_DAYS = 120

# Wire bounds (mirrors the backend schema).
MAX_FRAMES = 64
MAX_OPERATORS = 50
MAX_RAW_CHARS = 200_000
MAX_MESSAGE_CHARS = 512
MAX_CONTEXT_STRING = 256

# Uncaught Python exceptions: the same exception (type + top frames) is sent
# once per session, at most this many per session, and at most this many wait
# on disk for a signed-in session.
MAX_EXCEPTIONS_PER_SESSION = 20
MAX_PENDING_EXCEPTIONS = 50

# Timers: first harvest after start-up settles (login usually done), then a
# heartbeat that refreshes the session breadcrumb and retries what is pending.
FIRST_TICK_S = 20.0
TICK_S = 30.0
# A breadcrumb older than this, whose process is gone, matched no crash and
# is pruned.
SESSION_MAX_AGE_DAYS = 14
# A crash file belongs to a breadcrumb if it was written between the session's
# start and this long after its last heartbeat.
SESSION_MATCH_SLACK_S = 600
