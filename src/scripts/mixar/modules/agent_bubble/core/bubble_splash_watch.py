# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Splash-watcher for agent bubble auto-show.

Polls splash visibility and arms the autoshow when the splash goes
away (or never appeared within the grace window).
"""

import time as _time

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.agent_bubble.core.bubble_autoshow import arm_autoshow
from mixar.modules.agent_bubble.core.bubble_lifecycle import (
    has_agent_bubble_windows,
    reset_restored_bubbles_after_load,
)

logger = get_logger(__name__)

SPLASH_POLL_S = 0.3
SPLASH_GRACE_S = 5.0
_splash_watch_started_ts: float | None = None


def splash_watch_tick():
    """Wait for splash dismissal, then arm the autoshow."""
    global _splash_watch_started_ts

    try:
        from mixar.bootstrap import splash_menu
    except Exception:  # noqa: BLE001
        arm_autoshow(reset=True)
        return None

    if _splash_watch_started_ts is None:
        _splash_watch_started_ts = _time.monotonic()
    elapsed = _time.monotonic() - _splash_watch_started_ts

    if splash_menu.is_splash_visible():
        return SPLASH_POLL_S

    if has_agent_bubble_windows():
        logger.info("agent_bubble: restored startup bubble found, recreating clean overlay")
        reset_restored_bubbles_after_load()
        return None

    if getattr(bpy.data, "filepath", ""):
        logger.info("agent_bubble: existing file loaded, arming file-load autoshow")
        reset_restored_bubbles_after_load()
        return None

    if splash_menu.has_splash_ever_drawn():
        logger.info("agent_bubble: splash dismissed, arming autoshow")
        arm_autoshow(reset=True)
        return None

    if elapsed > SPLASH_GRACE_S:
        logger.info(
            "agent_bubble: splash never drew within %.1fs, arming autoshow anyway",
            SPLASH_GRACE_S,
        )
        arm_autoshow(reset=True)
        return None

    return SPLASH_POLL_S
