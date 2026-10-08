# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the account card's credit balance.

The card prints the credit balance as a number, exactly as the web
dashboard (``mixie-frontend`` ``DashboardPage.tsx``) does — no percentage
and no bar, so the two surfaces cannot disagree about a denominator.
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
# Plan classification
# ---------------------------------------------------------------------------

#: ``plan_slug`` values starting with this mark a trial (mirrors the web
#: dashboard's ``isTrialUser``).
TRIAL_SLUG_PREFIX = "trial"

#: Dashboard handoff targets for the popover CTAs.
HANDOFF_TARGET_BUY_CREDITS = "buy-credits"
HANDOFF_TARGET_PRICING = "pricing"

#: ``billing_interval`` the backend reports for a free-tier account holding
#: bonus credits (sign-up bonus, referral rewards, top-ups) and no monthly
#: allowance.
FREE_BILLING_INTERVAL = "free"
