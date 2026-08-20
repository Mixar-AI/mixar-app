# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update Check Trigger

Reusable orchestration for triggering an update check from any context
(startup timer, WebSocket notification, manual user action).

All heavy work runs on the main thread via ``bpy.app.timers``, so
``trigger_update_check()`` is safe to call from **any** thread.

Updating is browser-based: the toast's [Download] button opens the
downloads page — there is no in-app download or installer launch.
"""

import bpy

from mixar.config.logging_config import get_logger

from ...updates.constants import UpdateState

logger = get_logger(__name__)

# States that indicate an update flow is already active.  AVAILABLE counts:
# once an update is known, a background re-check has nothing to add — the
# badge and toast stay live until the user updates via the browser.
_ACTIVE_STATES = frozenset({
    UpdateState.CHECKING,
    UpdateState.AVAILABLE,
})

# Whether the in-flight check was requested explicitly by the user
# (Help → Check for Updates).  Interactive checks give feedback even when
# up to date or on failure, and ignore a previously skipped version.
# Only one check runs at a time (_ACTIVE_STATES guard), so a plain flag
# is race-safe; the callbacks consume and reset it.
_interactive_check = {"active": False}


# ============================================================================
# Public entry point
# ============================================================================


def trigger_update_check(interactive: bool = False) -> bool:
    """Trigger an update check if one is not already in progress.

    Safe to call from **any** thread.  Bounces work to the main thread
    via ``bpy.app.timers.register``.

    Args:
        interactive: True when the user explicitly asked (menu action) —
            shows "up to date"/failure feedback and bypasses skip-version.

    Returns:
        ``True`` if a check was scheduled, ``False`` if skipped because
        an update flow is already active.
    """
    from .state import get_update_state

    state = get_update_state()
    if state.state in _ACTIVE_STATES:
        logger.debug(
            "Skipping update check — already in state %s", state.state.value,
        )
        return False

    _interactive_check["active"] = interactive
    bpy.app.timers.register(_do_update_check, first_interval=0.0)
    logger.info("Update check scheduled on main thread (interactive=%s)", interactive)
    return True


# ============================================================================
# Main-thread timer callback
# ============================================================================


def _do_update_check() -> None:
    """Gather parameters and fire the async API call.

    Runs on the **main thread** (timer callback).  Returns ``None`` so
    the timer does not repeat.
    """
    try:
        from mixar.config.config import get_config
        from mixar.modules.common.api.services.update_service import (
            get_update_service,
        )

        from .state import get_update_state
        from .update_checker import (
            get_current_version,
            get_or_create_install_id,
            get_platform_key,
        )

        state = get_update_state()

        # Double-check guard (race window between scheduling and execution)
        if state.state in _ACTIVE_STATES:
            return None

        state.set_checking()

        platform = get_platform_key()
        version = get_current_version()
        config = get_config()
        channel = config.get("updates", {}).get("channel", "stable")
        install_id = get_or_create_install_id()

        logger.info(
            "Checking for updates: platform=%s, version=%s, channel=%s",
            platform,
            version,
            channel,
        )

        service = get_update_service()
        service.check_async(
            platform=platform,
            current_version=version,
            channel=channel,
            install_id=install_id,
            on_success=_on_check_success,
            on_error=_on_check_error,
        )

    except Exception as e:
        logger.error("Update check init failed: %s", e, exc_info=True)

    return None


# ============================================================================
# API callbacks (run on main thread via APIQueueProcessor)
# ============================================================================


def _on_check_success(response) -> None:
    """Handle the API response from the update check."""
    from .state import get_update_state
    from .update_checker import get_skipped_version, parse_update_response

    state = get_update_state()
    interactive = _interactive_check["active"]
    _interactive_check["active"] = False

    try:
        data = response.data if hasattr(response, "data") else {}
        info = parse_update_response(data)

        if info is None:
            logger.info("No update available")
            state.set_idle()
            _tag_topbar_redraw()
            if interactive:
                _push_up_to_date_toast()
            return

        logger.info(
            "Update available: %s -> %s (severity=%s, force=%s)",
            info.current_version,
            info.latest_version,
            info.severity,
            info.force_update,
        )
        state.set_available(info)

        # A skipped version only suppresses the toast — the update info is
        # still cached so the topbar badge stays visible until the user is
        # actually on the latest version.  Forced updates and explicit
        # user-requested checks always toast.
        if not is_forced(info) and not interactive:
            skipped = get_skipped_version()
            if skipped and skipped == info.latest_version:
                logger.info(
                    "Version %s was skipped by user — badge only, no toast",
                    info.latest_version,
                )
                _tag_topbar_redraw()
                return

        _push_update_available_toast(info)

    except Exception as e:
        logger.error("Failed to process update response: %s", e, exc_info=True)
        state.set_error(str(e))


def _on_check_error(error: Exception) -> None:
    """Handle update check failure — silent unless user-requested."""
    from .state import get_update_state

    interactive = _interactive_check["active"]
    _interactive_check["active"] = False

    logger.debug("Update check failed (silent): %s", error)
    get_update_state().set_idle()
    if interactive:
        _push_check_failed_toast()


# ============================================================================
# Toast helpers
# ============================================================================


def is_forced(info) -> bool:
    """A forced or unsupported update must be installed — no skipping."""
    return bool(info.force_update or info.unsupported)


def _tag_topbar_redraw():
    """Refresh the topbar update badge (main thread only).

    Usable directly or as a one-shot ``bpy.app.timers`` callback.
    """
    try:
        from ..ui.topbar_badge import tag_topbar_redraw

        tag_topbar_redraw()
    except Exception:
        pass
    return None


def _push_update_available_toast(info) -> None:
    """Push the sticky update toast; [Download] opens the downloads page.

    Forced/unsupported updates offer no Skip and are non-dismissible — the
    only path forward is to download the new version.
    """
    from ...notifications.store import NotificationAction, get_notification_store
    from ..constants import UPDATE_NOTIFICATION_ID

    forced = is_forced(info)

    body = f"Version {info.latest_version} is available."
    if forced:
        body += " This update is required to continue using Mixar."
    if info.changelog_summary:
        body += f"\n{info.changelog_summary}"

    actions = []
    if not forced:
        actions.append(NotificationAction(
            label="Skip", operator="mixar.dismiss_update", style="secondary",
        ))
    actions.append(NotificationAction(
        label="Download", operator="mixar.open_downloads_page", style="primary",
    ))

    get_notification_store().push(
        type_str="update",
        title="Mixar Update Required" if forced else "Mixar Update Available",
        body=body,
        priority="critical" if forced else "normal",
        actions=actions,
        ttl_ms=0,
        id=UPDATE_NOTIFICATION_ID,
        dismissible=not forced,
    )
    logger.info("Pushed 'update available' toast for v%s", info.latest_version)
    _tag_topbar_redraw()
    return None


def _push_up_to_date_toast() -> None:
    """Feedback for an interactive check that found no update."""
    from ...notifications.store import get_notification_store
    from ..constants import UPDATE_NOTIFICATION_ID
    from .update_checker import get_current_version

    get_notification_store().push(
        type_str="success",
        title="Mixar is up to date",
        body=f"You're running the latest version ({get_current_version()}).",
        priority="normal",
        ttl_ms=6000,
        id=UPDATE_NOTIFICATION_ID,
    )


def _push_check_failed_toast() -> None:
    """Feedback for an interactive check that could not reach the server."""
    from ...notifications.store import get_notification_store
    from ..constants import UPDATE_NOTIFICATION_ID

    get_notification_store().push(
        type_str="error",
        title="Could not check for updates",
        body="Check your internet connection and try again.",
        priority="normal",
        ttl_ms=6000,
        id=UPDATE_NOTIFICATION_ID,
    )
