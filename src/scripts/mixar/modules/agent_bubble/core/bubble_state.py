# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared mutable state for the agent bubble bootstrap.

All module-level flags and counters that multiple bubble sub-modules
need to read or write live here so they can be imported without
circular dependency issues.
"""

# Retry budgets
AUTOSHOW_RETRY_LIMIT = 30
LOAD_AUTOSHOW_RETRY_LIMIT = 40

autoshow_attempts = 0
load_autoshow_attempts = 0
autoshow_start_minimised = False
# Latched when the bubble window could not be created (no GL context for it,
# e.g. an AMD integrated GPU on Windows): autoshow and the file-load retry
# stop instead of re-failing. The next file load clears it (one attempt per
# load); an explicit open still tries and clears it on success.
window_unavailable = False

# User-dismissal tracking
user_explicitly_closed = False
closed_for_save = False
# > 0 while a snapshot copy (turn checkpoint) is being written: on_save_pre
# keeps the island and pill open for that save (see keep_windows_for_snapshot).
snapshot_save_depth = 0
