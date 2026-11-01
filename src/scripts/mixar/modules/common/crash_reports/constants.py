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
# its own temp dir; its supervisor (common/render_worker) moves each crashed
# worker's log to <tmp>/mixar_render_worker_crashes/<pid>-<kind>-<n>.crash.txt.
# These are our own copies: deleted once handled, or past MAX_FILE_AGE_DAYS.
WORKER_CRASH_DIR = "mixar_render_worker_crashes"
WORKER_CRASH_GLOB = (WORKER_CRASH_DIR, "*.crash.txt")
# A log still in the worker's own temp dir (the supervisor died before moving
# it): <tmp>/mixar_render_worker/<app pid>/worker-<kind>/tmp/. Read only.
WORKER_TMP_CRASH_GLOB = ("mixar_render_worker", "*", "worker-*", "tmp", "*.crash.txt")
# Python's faulthandler writes the Python stacks of a native crash to a file
# per process: <state>/pyfault-<pid>.txt for the app, <worker tmp>/
# pyfault-<pid>.txt for a render worker. The supervisor moves a crashed
# worker's file next to its crash log as <pid>-<kind>-<n>.pyfault.txt.
PYFAULT_PREFIX = "pyfault-"
PYFAULT_SUFFIX = ".txt"
WORKER_PYFAULT_SUFFIX = ".pyfault.txt"
# A faulthandler dump belongs to a crash file written within this long of it
# (macOS writes an .ips some seconds after the process died).
PYFAULT_MATCH_S = 120
# Windows also dumps on first-chance exceptions that are then handled: past
# this size the running session's file is emptied.
PYFAULT_MAX_BYTES = 1024 * 1024
MACOS_REPORTS_DIR = "~/Library/Logs/DiagnosticReports"
MACOS_REPORT_GLOB = "Mixar*.ips"
MAX_FILE_AGE_DAYS = 30
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_REPORTS_PER_LAUNCH = 10
SENT_LEDGER_DAYS = 120

# Wire bounds (mirrors the backend schema).
MAX_FRAMES = 64
MAX_PYTHON_STACK = 64
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
