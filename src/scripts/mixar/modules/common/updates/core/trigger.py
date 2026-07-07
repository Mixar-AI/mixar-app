# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update Check Trigger

Reusable orchestration for triggering an update check from any context
(startup timer, WebSocket notification, manual user action).

All heavy work runs on the main thread via ``bpy.app.timers``, so
``trigger_update_check()`` is safe to call from **any** thread.
"""

import threading

import bpy

from mixar.config.logging_config import get_logger

from ...updates.constants import UpdateState

logger = get_logger(__name__)

# States that indicate an update flow is already active.
_ACTIVE_STATES = frozenset({
    UpdateState.CHECKING,
    UpdateState.DOWNLOADING,
    UpdateState.READY,
    UpdateState.INSTALLING,
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
    from mixar.config.config import get_config

    from .downloader import get_cached_installer
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
            if interactive:
                _push_up_to_date_toast()
            return

        # Skip check (unless forced, or the user asked explicitly)
        if not is_forced(info) and not interactive:
            skipped = get_skipped_version()
            if skipped and skipped == info.latest_version:
                logger.info("Version %s was skipped by user", info.latest_version)
                state.set_idle()
                return

        logger.info(
            "Update available: %s -> %s (severity=%s, force=%s)",
            info.current_version,
            info.latest_version,
            info.severity,
            info.force_update,
        )

        # Store update info in state
        with state._lock:
            state._update_info = info

        # Check cache first
        cached = get_cached_installer(info)
        if cached:
            logger.info("Installer already cached: %s", cached)
            state.set_ready(cached)
            _push_ready_toast(info)
            return

        # Download only on explicit user action ([Update]) unless the user
        # opted into auto-download via config (default: False). Either path is
        # visible — begin_download shows a live progress toast.
        config = get_config()
        auto_download = config.get("updates", {}).get("auto_download", False)

        if auto_download and info.download_url:
            begin_download(info)
        else:
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
# Download orchestration
# ============================================================================

# Cadence at which the downloading toast is re-pushed with fresh progress.
_PROGRESS_INTERVAL = 0.4


def begin_download(info) -> None:
    """Start (or resume from cache) the installer download for *info*.

    Main-thread safe. Called by ``_on_check_success`` (auto-download) and by
    the ``mixar.start_update_download`` operator ([Update] / [Retry]).
    """
    from .downloader import get_cached_installer
    from .state import get_update_state

    state = get_update_state()

    # Guard against re-entrancy while a download / install is in flight.
    if state.state in (UpdateState.DOWNLOADING, UpdateState.INSTALLING):
        logger.debug(
            "begin_download ignored — already in state %s", state.state.value,
        )
        return

    # A verified cached installer skips straight to the ready toast.
    cached = get_cached_installer(info)
    if cached:
        logger.info("Installer already cached: %s", cached)
        state.set_ready(cached)
        _push_ready_toast(info)
        return

    state.set_downloading(info)
    _push_downloading_toast()
    _ensure_progress_timer()
    _start_background_download(info)


def _ensure_progress_timer() -> None:
    """Register the progress-refresh timer if it is not already running."""
    if not bpy.app.timers.is_registered(_progress_tick):
        bpy.app.timers.register(_progress_tick, first_interval=_PROGRESS_INTERVAL)


def _progress_tick():
    """Re-push the downloading toast with current progress (main thread).

    Reads live state each tick — never closes over stale values. Returns an
    interval to repeat while downloading, or ``None`` to stop (including once
    a cancel has been requested, so the dismissed toast can't flicker back).
    """
    from .state import get_update_state

    state = get_update_state()
    if state.state != UpdateState.DOWNLOADING or state.cancel_requested:
        return None

    _push_downloading_toast()
    return _PROGRESS_INTERVAL


def _start_background_download(info) -> None:
    """Kick off a daemon thread to download the installer.

    ``begin_download`` owns the DOWNLOADING transition, the progress toast,
    and the refresh timer; this only runs the transfer and schedules the
    result toast on the main thread.
    """
    from .state import get_update_state

    state = get_update_state()

    def _run():
        from .downloader import download_update

        path = download_update(info)
        if path:
            state.set_ready(path)
            bpy.app.timers.register(
                lambda: _push_ready_toast(info), first_interval=0.0,
            )
        elif not state.cancel_requested:
            state.set_error("Download failed")
            logger.warning(
                "Installer download failed for %s", info.latest_version,
            )
            bpy.app.timers.register(
                lambda: _push_download_failed_toast(info), first_interval=0.0,
            )
        else:
            # Cancelled: the thread owns the return to IDLE (which clears the
            # cancel flag) so no stale ready/failed toast is shown afterwards.
            logger.info("Download cancelled by user for %s", info.latest_version)
            state.set_idle()

    thread = threading.Thread(
        target=_run, daemon=True, name="MixarUpdateDownload",
    )
    state.set_download_thread(thread)
    thread.start()
    logger.info("Background download started for %s", info.latest_version)


# ============================================================================
# Toast helpers
# ============================================================================


def is_forced(info) -> bool:
    """A forced or unsupported update must be installed — no skipping."""
    return bool(info.force_update or info.unsupported)


def _push_update_toast(info, ready: bool) -> None:
    """Push the sticky update toast.

    ``ready`` selects the wording (installer downloaded vs. merely
    available).  Forced/unsupported updates render without Skip or a
    close button so the only path forward is Install.
    """
    from ...notifications.store import NotificationAction, get_notification_store
    from ..constants import UPDATE_NOTIFICATION_ID

    forced = is_forced(info)

    state_word = "ready to install" if ready else "available"
    body = f"Version {info.latest_version} is {state_word}."
    if forced:
        body += " This update is required to continue using Mixar."
    if info.changelog_summary:
        body += f"\n{info.changelog_summary}"

    actions = []
    if not forced:
        actions.append(NotificationAction(
            label="Skip",
            operator="mixar.dismiss_update",
            style="secondary",
        ))
    actions.append(NotificationAction(
        label="Install Update",
        operator="mixar.install_update",
        style="primary",
    ))

    get_notification_store().push(
        type_str="update",
        title="Mixar Update Required" if forced else
              ("Mixar Update Ready" if ready else "Mixar Update Available"),
        body=body,
        priority="critical" if forced else ("high" if ready else "normal"),
        actions=actions,
        ttl_ms=0,
        id=UPDATE_NOTIFICATION_ID,
        dismissible=not forced,
    )
    logger.info(
        "Pushed update toast for v%s (ready=%s, forced=%s)",
        info.latest_version, ready, forced,
    )
    return None  # For use as timer callback


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


def _push_ready_toast(info) -> None:
    """Push a sticky toast telling the user the update is ready to install."""
    return _push_update_toast(info, ready=True)


def _push_update_available_toast(info) -> None:
    """Notify that an update exists; the download starts only on [Update].

    Forced/unsupported updates offer no Skip and are non-dismissible — the
    only path forward is to update.
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
        label="Update", operator="mixar.start_update_download", style="primary",
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
    return None


def _push_downloading_toast() -> None:
    """Push the live download-progress toast (reads state internally).

    Non-forced downloads offer Cancel; a required update has no escape hatch.
    """
    from ...notifications.store import NotificationAction, get_notification_store
    from ..constants import UPDATE_NOTIFICATION_ID
    from .state import get_update_state

    state = get_update_state()
    info = state.update_info
    if info is None:
        return None

    forced = is_forced(info)
    progress = state.progress
    pct = int(progress.percent)
    # Percent + size go on their own line under the "Downloading <ver>…" head.
    body = f"Downloading {info.latest_version}…"
    if progress.total_bytes > 0:
        done_mb = progress.downloaded_bytes / 1e6
        total_mb = progress.total_bytes / 1e6
        body += f"\n{pct}% ({done_mb:.0f}/{total_mb:.0f} MB)"
    else:
        body += f"\n{pct}%"

    actions = []
    if not forced:
        actions.append(NotificationAction(
            label="Cancel", operator="mixar.cancel_update", style="secondary",
        ))

    get_notification_store().push(
        type_str="update",
        title="Downloading update…",
        body=body,
        priority="high",
        actions=actions,
        ttl_ms=0,
        id=UPDATE_NOTIFICATION_ID,
        dismissible=not forced,
    )
    return None


def _push_download_failed_toast(info) -> None:
    """Push a failure toast offering in-app retry or a browser fallback.

    Stays non-dismissible for forced updates so it can't be swiped away.
    """
    from ...notifications.store import NotificationAction, get_notification_store
    from ..constants import UPDATE_NOTIFICATION_ID

    forced = is_forced(info)
    body = (
        f"Couldn't download {info.latest_version}. "
        "Check your connection and retry, or download it from the website."
    )

    get_notification_store().push(
        type_str="error",
        title="Update download failed",
        body=body,
        priority="high",
        actions=[
            NotificationAction(
                label="Retry",
                operator="mixar.start_update_download",
                style="primary",
            ),
            NotificationAction(
                label="Download in browser",
                operator="mixar.open_downloads_page",
                style="secondary",
            ),
        ],
        ttl_ms=0,
        id=UPDATE_NOTIFICATION_ID,
        dismissible=not forced,
    )
    logger.warning("Pushed 'download failed' toast for v%s", info.latest_version)
    return None
