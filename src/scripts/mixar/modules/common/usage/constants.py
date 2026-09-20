# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the account card's usage meter.

Thresholds intentionally mirror the web dashboard's usage bar
(``mixie-frontend`` ``DashboardPage.tsx``) so a user reading "18% left"
in Mixar and "82% used" on the website is looking at the same number
computed the same way — the backend's ``usage_pct`` is the one source of
truth for both and is never recomputed client-side.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Refresh cadence
# ---------------------------------------------------------------------------

#: How long a fetched snapshot stays fresh before the draw path asks for a
#: refresh. Matches the web dashboard's 60s ``refetchInterval``.
USAGE_TTL_SECONDS = 60.0

#: Floor between two network fetches, however often a refresh is requested.
#: The top bar redraws constantly; without this a hover could spam the API.
USAGE_MIN_FETCH_GAP_SECONDS = 10.0

#: Delay before the first fetch after login/startup, so the HTTP executor
#: and token refresh are settled first (same rationale as update_checker).
USAGE_INITIAL_DELAY_SECONDS = 4.0

#: Network timeout for a single status fetch. Short — a stale meter is far
#: better than a blocked worker.
USAGE_REQUEST_TIMEOUT_SECONDS = 10.0

# ---------------------------------------------------------------------------
# Display thresholds — evaluated on credits REMAINING, not used
# ---------------------------------------------------------------------------

#: Below this % remaining the meter turns red and nudges to top up.
USAGE_CRITICAL_PCT = 20.0

#: Below this % remaining the meter turns amber.
USAGE_WARNING_PCT = 50.0

#: Severity keys returned by :func:`core.state.usage_severity`.
SEVERITY_OK = 'OK'
SEVERITY_WARNING = 'WARNING'
SEVERITY_CRITICAL = 'CRITICAL'

# ---------------------------------------------------------------------------
# Plan classification
# ---------------------------------------------------------------------------

#: ``plan_slug`` values starting with this mark a trial (mirrors the web
#: dashboard's ``isTrialUser``). Trial users cannot buy credit top-ups.
TRIAL_SLUG_PREFIX = "trial"

#: Dashboard handoff targets for the popover CTAs.
HANDOFF_TARGET_BUY_CREDITS = "buy-credits"
HANDOFF_TARGET_PRICING = "pricing"
