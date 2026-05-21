# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent bubble auto-show logic.

Context finding, invoke wrapper, the autoshow retry loop, and the
arm_autoshow helper that schedules the timer.
"""

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.agent_bubble.core.bubble_lifecycle import (
    has_agent_bubble_windows,
    is_agent_bubble_window,
)
from mixar.modules.agent_bubble.core.bubble_state import (
    AUTOSHOW_RETRY_LIMIT,
)
from . import bubble_state as _st

logger = get_logger(__name__)


def find_target_context():
    """Pick a (window, area, region) tuple a popup can be invoked from.

    Prefers a 3D viewport; falls back to any area in any window. Returns
    None when there's nothing usable yet.
    """
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                region = next(
                    (r for r in area.regions if r.type == 'WINDOW'), None
                )
                if region is not None:
                    return window, area, region
    for window in wm.windows:
        if not window.screen.areas:
            continue
        area = window.screen.areas[0]
        region = next(
            (r for r in area.regions if r.type == 'WINDOW'), None
        )
        if region is not None:
            return window, area, region
    return None


def try_invoke_bubble(start_minimised: bool = False) -> bool:
    """Invoke the bubble popup. Returns True on success."""
    target = find_target_context()
    if target is None:
        logger.info("agent_bubble: no usable window/area yet")
        return False
    window, area, region = target

    try:
        with bpy.context.temp_override(
            window=window, screen=window.screen, area=area, region=region
        ):
            if start_minimised:
                result = bpy.ops.mixar.agent_bubble_show_window(start_minimised=True)
            else:
                result = bpy.ops.mixar.agent_bubble_open_window()
        if 'CANCELLED' in result:
            logger.info("agent_bubble: invoke returned %s", result)
            return False
        created = any(
            is_agent_bubble_window(window)
            for window in bpy.context.window_manager.windows
        )
        if not created:
            logger.info("agent_bubble: invoke finished but no AGENT_BUBBLE window exists")
        return created
    except (AttributeError, RuntimeError) as e:
        print(f"[agent_bubble] BUBBLE INVOKE FAILED: {e!r}")
        logger.info("agent_bubble: invoke deferred (%s)", e)
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("agent_bubble: invoke failed: %s", e)
        return False


_autoshow_in_progress = False


def autoshow_bubble():
    """One-shot timer that retries until the popup appears."""
    global _autoshow_in_progress
    if _autoshow_in_progress:
        return 0.5
    _autoshow_in_progress = True
    try:
        return _autoshow_bubble_inner()
    finally:
        _autoshow_in_progress = False


def _autoshow_bubble_inner():
    _st.autoshow_attempts += 1

    try:
        from mixar.bootstrap import splash_menu
        if splash_menu.is_splash_visible():
            _st.autoshow_attempts -= 1
            return 0.5
    except Exception:  # noqa: BLE001
        pass

    if try_invoke_bubble(start_minimised=_st.autoshow_start_minimised):
        logger.info(
            "agent_bubble: shown after %d attempt(s) (minimised=%s)",
            _st.autoshow_attempts,
            _st.autoshow_start_minimised,
        )
        _st.autoshow_attempts = 0
        _st.autoshow_start_minimised = False
        return None

    if _st.autoshow_attempts >= AUTOSHOW_RETRY_LIMIT:
        logger.warning(
            "agent_bubble: giving up after %d attempts — "
            "use the 'Open Agent' button in the top bar to invoke manually",
            _st.autoshow_attempts,
        )
        _st.autoshow_attempts = 0
        _st.autoshow_start_minimised = False
        return None
    return 0.5


def arm_autoshow(reset: bool = True, start_minimised: bool = False) -> None:
    """Arm (or re-arm) the auto-show timer. Idempotent."""
    if reset:
        _st.autoshow_attempts = 0
    _st.autoshow_start_minimised = start_minimised
    if not bpy.app.timers.is_registered(autoshow_bubble):
        bpy.app.timers.register(autoshow_bubble, first_interval=0.5)
