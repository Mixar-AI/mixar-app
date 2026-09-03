# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update Check Trigger

Reusable orchestration for triggering an update check from any context
(startup timer, WebSocket notification, manual user action), plus the
single state-driven renderer for the update toast.

All heavy work runs on the main thread via ``bpy.app.timers``, so
``trigger_update_check()`` is safe to call from **any** thread.

When an update is found the installer starts downloading in the
background, so the toast's primary action can be **Restart & Update**
rather than a trip to the browser.  The browser download stays as the
fallback whenever this install cannot update itself (an unsupported
platform, a read-only install, a release with no installer artifact) or
the download failed.
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
# up to date or on failure, and toast even if the version was announced
# already — the user just asked.
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
            shows "up to date"/failure feedback and toasts even for an
            already-announced version.

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
    from .toasts import (
        push_update_available_toast,
        push_up_to_date_toast,
        tag_topbar_redraw,
    )
    from .update_checker import (
        ANNOUNCE_AVAILABLE,
        get_announced_stage,
        is_forced,
        parse_update_response,
        set_announced_stage,
    )

    state = get_update_state()
    interactive = _interactive_check["active"]
    _interactive_check["active"] = False

    try:
        data = response.data if hasattr(response, "data") else {}
        info = parse_update_response(data)

        if info is None:
            logger.info("No update available")
            state.set_idle()
            tag_topbar_redraw()
            if interactive:
                push_up_to_date_toast()
            return

        logger.info(
            "Update available: %s -> %s (severity=%s, force=%s)",
            info.current_version,
            info.latest_version,
            info.severity,
            info.force_update,
        )
        state.set_available(info)

        # Staging always starts: it is the invisible half of "seamless",
        # and the badge reports it either way.
        _start_installer_download(info)

        # An already-announced version gets the badge, not a second toast.
        # The update info stays cached, so the badge remains visible until
        # the user is actually on the latest version and re-opens the toast
        # on click.  Forced updates and explicit user-requested checks
        # always toast.
        if not is_forced(info) and not interactive:
            if get_announced_stage(info.latest_version):
                logger.info(
                    "Version %s already announced — badge only, no toast",
                    info.latest_version,
                )
                tag_topbar_redraw()
                return

        set_announced_stage(info.latest_version, ANNOUNCE_AVAILABLE)
        push_update_available_toast(info)

    except Exception as e:
        logger.error("Failed to process update response: %s", e, exc_info=True)
        state.set_error(str(e))


def _on_check_error(error: Exception) -> None:
    """Handle update check failure — silent unless user-requested."""
    from .state import get_update_state
    from .toasts import push_check_failed_toast

    interactive = _interactive_check["active"]
    _interactive_check["active"] = False

    logger.debug("Update check failed (silent): %s", error)
    get_update_state().set_idle()
    if interactive:
        push_check_failed_toast()


# ============================================================================
# Installer download kick-off
# ============================================================================


def _start_installer_download(info) -> None:
    """Begin staging the installer unless the user turned that off.

    Failure here is not fatal: :mod:`install_flow` records why, and the
    toast falls back to the browser download.
    """
    try:
        from mixar.config.config import get_config

        if not get_config().get("updates", {}).get("auto_download", True):
            # The toast still offers Restart & Update; the click starts
            # the download instead of a background one starting it.
            logger.info("auto_download disabled — staging on demand only")
            return
    except Exception:  # noqa: BLE001 - config is advisory here
        pass

    try:
        from .install_flow import start_download

        start_download(info)
    except Exception:  # noqa: BLE001 - never break the update check
        logger.error("Could not start the installer download", exc_info=True)
