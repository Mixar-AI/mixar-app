# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish to Web telemetry (``web_publish``).

The funnel start → outcome, content-free: how the publish was started, a
few booleans and an outcome enum. Never a title, description, slug, URL,
path or error text — the GLB export itself is already counted by
``export.completed`` (``via="web_publish"``).
"""

from .capture import capture
from .constants import EVENT_WEB_PUBLISH_FINISHED, EVENT_WEB_PUBLISH_STARTED

VIAS = ("panel", "agent")
OUTCOMES = ("ready", "failed", "cancelled")


def capture_publish_started(via: str, update: bool, include_animation: bool,
                            *, context=None) -> None:
    capture(EVENT_WEB_PUBLISH_STARTED, {
        "via": via if via in VIAS else "other",
        "update": bool(update),
        "include_animation": bool(include_animation),
    }, context=context)


def capture_publish_finished(via: str, outcome: str, *, context=None) -> None:
    capture(EVENT_WEB_PUBLISH_FINISHED, {
        "via": via if via in VIAS else "other",
        "outcome": outcome if outcome in OUTCOMES else "failed",
    }, context=context)
