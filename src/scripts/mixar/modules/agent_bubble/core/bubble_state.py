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

# User-dismissal tracking
user_explicitly_closed = False
closed_for_save = False
