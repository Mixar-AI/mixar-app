# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Out-of-credits banner telemetry.

The banner is the moment a user hits the paywall, so these two events are
the funnel from "ran out" to "upgraded / referred / applied / walked away".
Both carry one allowlisted enum and nothing else.
"""

from .capture import capture
from .constants import EVENT_CREDITS_BANNER_ACTION, EVENT_CREDITS_BANNER_SHOWN

BANNER_TRIGGERS = frozenset({"push", "http_402", "chat", "job", "mask_tool", "manual"})
BANNER_ACTIONS = frozenset({"upgrade", "refer", "creator", "dismiss"})


def capture_credits_banner_shown(trigger: str, *, context=None) -> None:
    """The banner opened; ``trigger`` is which signal opened it."""
    capture(
        EVENT_CREDITS_BANNER_SHOWN,
        {"trigger": trigger if trigger in BANNER_TRIGGERS else "other"},
        context=context,
    )


def capture_credits_banner_action(action: str, *, context=None) -> None:
    """The user chose a button, or dismissed the banner."""
    action = (action or "").lower()
    capture(
        EVENT_CREDITS_BANNER_ACTION,
        {"action": action if action in BANNER_ACTIONS else "dismiss"},
        context=context,
    )
