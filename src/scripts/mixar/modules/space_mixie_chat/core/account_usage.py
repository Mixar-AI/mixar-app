# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Session-only account usage cache and asynchronous refresh helpers."""

from __future__ import annotations

import threading
import time

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.auth.core.auth import get_user_info

logger = get_logger(__name__)

STALE_AFTER_SECONDS = 60.0

# True while a stale-check timer is queued. Kept separate from
# ``mixie_account_loading`` (which means "a fetch is in flight") so a dropped
# timer can never wedge the refresh button or the "Refreshing..." label.
_schedule_pending = False


def apply_user_info(wm, data: dict) -> None:
    """Apply a successful ``/auth/me`` payload to session-only RNA state."""
    wm.mixie_account_credits = max(0, int(data.get("credits", 0) or 0))
    wm.mixie_account_plan_name = (
        data.get("plan_name") or data.get("plan_slug") or "Free"
    )
    trial_days = data.get("trial_days_remaining")
    wm.mixie_account_trial_days = int(trial_days) if trial_days is not None else -1
    wm.mixie_account_team_name = data.get("team_name") or ""
    wm.mixie_account_team_role = data.get("team_role") or ""
    wm.mixie_account_team_is_active = bool(data.get("team_is_active", False))
    wm.mixie_account_loaded = True
    wm.mixie_account_loading = False
    wm.mixie_account_error = ""
    wm.mixie_account_refreshed_at = time.monotonic()


def clear(wm) -> None:
    """Clear account data when the authenticated user changes or logs out."""
    for attr, value in (
        ("mixie_account_credits", 0),
        ("mixie_account_plan_name", ""),
        ("mixie_account_trial_days", -1),
        ("mixie_account_team_name", ""),
        ("mixie_account_team_role", ""),
        ("mixie_account_team_is_active", False),
        ("mixie_account_loaded", False),
        ("mixie_account_loading", False),
        ("mixie_account_error", ""),
        ("mixie_account_refreshed_at", 0.0),
    ):
        if hasattr(wm, attr):
            setattr(wm, attr, value)


def is_stale(wm) -> bool:
    refreshed_at = float(getattr(wm, "mixie_account_refreshed_at", 0.0))
    return (
        not getattr(wm, "mixie_account_loaded", False)
        or time.monotonic() - refreshed_at >= STALE_AFTER_SECONDS
    )


def _redraw_profile() -> None:
    """Redraw regular and global areas so the top-bar popover updates."""
    try:
        for window in bpy.context.window_manager.windows:
            areas = list(window.screen.areas)
            areas.extend(getattr(window, "global_areas", ()))
            for area in areas:
                area.tag_redraw()
    except Exception as exc:
        logger.debug("Account profile redraw failed: %s", exc)


def request_refresh(wm, *, force: bool = False) -> bool:
    """Start one background refresh, returning whether work was scheduled."""
    if getattr(wm, "mixie_account_loading", False):
        return False
    if not force and not is_stale(wm):
        return False

    wm.mixie_account_loading = True
    wm.mixie_account_error = ""

    def _fetch() -> None:
        result = get_user_info()

        def _apply() -> None:
            try:
                current_wm = bpy.context.window_manager
                if not getattr(current_wm, "mixie_chat_is_logged_in", False):
                    # Logged out while the request was in flight — never write
                    # the previous user's balance back over the cleared state.
                    current_wm.mixie_account_loading = False
                    _redraw_profile()
                    return None
                if result and result.get("status") == "success":
                    apply_user_info(current_wm, result.get("data") or {})
                    scene = getattr(bpy.context, "scene", None)
                    if scene is not None and hasattr(scene, "mixie_chat_credits"):
                        scene.mixie_chat_credits = current_wm.mixie_account_credits
                else:
                    current_wm.mixie_account_loading = False
                    current_wm.mixie_account_error = (
                        (result or {}).get("message") or "Could not refresh account."
                    )
            except Exception as exc:
                logger.warning("Account usage apply failed: %s", exc)
            _redraw_profile()
            return None

        bpy.app.timers.register(_apply, first_interval=0.0)

    threading.Thread(
        target=_fetch, daemon=True, name="MixarAccountUsageRefresh"
    ).start()
    return True


def schedule_stale_refresh(wm) -> None:
    """Defer a stale check out of panel draw; repeated calls are coalesced.

    The latch is a module global rather than RNA state: this runs from
    ``draw()``, which must not write RNA, and a lost timer must not leave the
    UI stuck reporting an in-flight fetch.
    """
    global _schedule_pending
    if (
        _schedule_pending
        or getattr(wm, "mixie_account_loading", False)
        or not is_stale(wm)
    ):
        return

    def _start() -> None:
        global _schedule_pending
        _schedule_pending = False
        current_wm = bpy.context.window_manager
        if getattr(current_wm, "mixie_chat_is_logged_in", False):
            request_refresh(current_wm)
        return None

    _schedule_pending = True
    bpy.app.timers.register(_start, first_interval=0.0)
