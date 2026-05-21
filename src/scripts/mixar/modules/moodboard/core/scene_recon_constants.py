# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared constants for the Scene Reconstruction pipeline."""

# Terminal job statuses that indicate polling should stop
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "expired"}

# Polling intervals: slow during GPU processing, fast during progressive delivery
POLL_INTERVAL_PHASE1 = 2.0   # GPU processing: slow updates
POLL_INTERVAL_PHASE2 = 1.0   # Progressive delivery: fast updates (backend rate limit: 60/min)

# Maximum concurrent GLB downloads
MAX_CONCURRENT_DOWNLOADS = 5
