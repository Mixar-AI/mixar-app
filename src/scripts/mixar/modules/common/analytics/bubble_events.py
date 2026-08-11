# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Deduplicated Agent Bubble telemetry."""

from .capture import capture
from .constants import EVENT_BUBBLE_STATE

_last_state: str | None = None


def capture_bubble_state(state: str, *, context=None) -> None:
    global _last_state
    if state == _last_state:
        return
    capture(EVENT_BUBBLE_STATE, {"state": state}, context=context)
    _last_state = state


def note_programmatic_bubble_state(state: str) -> None:
    """Record a product-driven transition so it is not reported as user intent.

    Without this the dedup guard goes stale: a programmatic minimise leaves
    ``_last_state`` on the pre-change value, so the user's next genuine change
    looks like a repeat and gets swallowed.
    """
    global _last_state
    _last_state = state


def reset_bubble_state() -> None:
    global _last_state
    _last_state = None
