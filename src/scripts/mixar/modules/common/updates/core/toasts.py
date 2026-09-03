# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update Toasts

Every notification the update system shows, in one place, rendered from
the current :mod:`state` rather than from whatever the caller happened to
know.  One toast id (``UPDATE_NOTIFICATION_ID``) is reused throughout, so
"available", "downloading", "ready to install" and "update failed" are
successive renderings of the same toast instead of a pile-up.
"""

from mixar.config.logging_config import get_logger

from .update_checker import is_forced

logger = get_logger(__name__)


def tag_topbar_redraw():
    """Refresh the topbar update badge (main thread only).

    Usable directly or as a one-shot ``bpy.app.timers`` callback.
    """
    try:
        from ..ui.topbar_badge import tag_topbar_redraw as _badge_redraw

        _badge_redraw()
    except Exception:
        pass
    return None


def _format_size(num_bytes) -> str:
    if num_bytes <= 0:
        return ""
    megabytes = num_bytes / (1024 * 1024)
    if megabytes >= 1024:
        return f"{megabytes / 1024:.1f} GB"
    return f"{megabytes:.0f} MB"


def _download_body(state) -> str:
    """Progress line for a download the user is waiting on."""
    transferred, total = state.download_bytes
    percent = int(round(state.download_progress * 100))
    if total > 0:
        return f"{percent}% — {_format_size(transferred)} of {_format_size(total)}"
    if transferred > 0:
        return f"{_format_size(transferred)} downloaded"
    return "Starting download…"


def push_downloading_toast(info) -> None:
    """The user pressed Restart & Update before the download had finished.

    A forced update keeps its non-dismissible, uncancellable character
    here too — otherwise cancelling the download would be a back door out
    of a toast that is deliberately impossible to dismiss.
    """
    from ...notifications.store import NotificationAction, get_notification_store
    from ..constants import UPDATE_NOTIFICATION_ID
    from .state import get_update_state

    forced = is_forced(info)
    actions = [] if forced else [NotificationAction(
        label="Cancel", operator="mixar.cancel_update_download", style="secondary",
    )]

    get_notification_store().push(
        type_str="update",
        title=f"Downloading Mixar {info.latest_version}",
        body=(
            f"{_download_body(get_update_state())}\n"
            "Mixar will restart to finish updating."
        ),
        priority="critical" if forced else "normal",
        actions=actions,
        ttl_ms=0,
        id=UPDATE_NOTIFICATION_ID,
        dismissible=not forced,
    )


def push_update_available_toast(info) -> None:
    """Push the sticky update toast for the current install state.

    One toast id, one renderer: whichever of "available", "ready to
    install", "downloading" or "download failed" is true right now
    decides the wording and the buttons.  Dismissal is the only way out
    and it is per-session; what stops the toast returning on the next
    launch is the announcement record, not a user choice.
    Forced/unsupported updates are non-dismissible — the only way
    forward is to update.
    """
    from ...notifications.store import NotificationAction, get_notification_store
    from ..constants import UPDATE_NOTIFICATION_ID, InstallState
    from .state import get_update_state

    state = get_update_state()
    install_state = state.install_state

    if install_state is InstallState.DOWNLOADING and state.install_requested:
        push_downloading_toast(info)
        tag_topbar_redraw()
        return None

    forced = is_forced(info)
    # IDLE counts when the release ships a verifiable installer and nothing
    # has ruled self-install out — that is the state after a cancelled
    # download, and with auto_download off. Offering the browser there would
    # strand the user on the one path we are trying to replace; the button
    # restarts the download instead (see install_flow.plan_restart).
    can_self_install = install_state in (
        InstallState.READY, InstallState.DOWNLOADING, InstallState.INSTALLING,
    ) or (
        install_state is InstallState.IDLE
        and not state.blocked_reason
        and bool(info.download_url and info.download_sha256)
    )

    if install_state is InstallState.READY:
        title = "Mixar Update Ready"
        body = f"Version {info.latest_version} is ready to install."
    else:
        # No percentage here, deliberately. Staging runs in the background
        # and the user has not asked to wait on it; the topbar badge shows
        # "Downloading 45%" for anyone who wants the detail. Progress
        # belongs in the toast only once the user has pressed Restart &
        # Update and is actually waiting — see push_downloading_toast.
        title = "Mixar Update Required" if forced else "Mixar Update Available"
        body = f"Version {info.latest_version} is available."

    if forced:
        body += " This update is required to continue using Mixar."
    if can_self_install:
        body += " Mixar will restart to apply it."
    if info.changelog_summary:
        body += f"\n{info.changelog_summary}"
    # The reason the primary button fell back to the browser. Without it a
    # failed background download is indistinguishable from a release that
    # never supported self-install — invisible unless a console is open.
    if install_state is InstallState.FAILED and state.install_error:
        body += f"\n{state.install_error} — use Download to update via your browser."

    actions = []
    if can_self_install:
        actions.append(NotificationAction(
            label="Restart & Update", operator="mixar.restart_to_update",
            style="primary",
        ))
    else:
        actions.append(NotificationAction(
            label="Download", operator="mixar.open_downloads_page", style="primary",
        ))

    get_notification_store().push(
        type_str="update",
        title=title,
        body=body,
        priority="critical" if forced else "normal",
        actions=actions,
        ttl_ms=0,
        id=UPDATE_NOTIFICATION_ID,
        dismissible=not forced,
    )
    logger.info(
        "Pushed update toast for v%s (install_state=%s)",
        info.latest_version, install_state.value,
    )
    tag_topbar_redraw()
    return None


def push_install_aborted_toast() -> None:
    """Mixar was asked to quit for an update and didn't.

    The helper has been killed and the staged installer is intact, so the
    honest message is "nothing happened, click again" — not an error the
    user has to interpret.
    """
    from ...notifications.store import NotificationAction, get_notification_store
    from ..constants import UPDATE_NOTIFICATION_ID
    from .state import get_update_state

    info = get_update_state().update_info
    version = f" {info.latest_version}" if info else ""

    get_notification_store().push(
        type_str="warning",
        title="Update paused",
        body=(
            "Mixar didn't close, so the update was not installed.\n"
            f"Click Restart & Update to install{version} again."
        ),
        priority="normal",
        actions=[NotificationAction(
            label="Restart & Update", operator="mixar.restart_to_update",
            style="primary",
        )],
        ttl_ms=0,
        id=UPDATE_NOTIFICATION_ID,
        dismissible=True,
    )
    tag_topbar_redraw()


def refresh_update_toast() -> None:
    """Re-render the update toast in place, if it is on screen.

    Called whenever install state moves.  A toast the user dismissed
    stays dismissed — re-pushing it on every progress tick would make it
    impossible to get rid of.
    """
    from ...notifications.store import get_notification_store
    from ..constants import UPDATE_NOTIFICATION_ID
    from .state import get_update_state

    state = get_update_state()
    info = state.update_info
    if info is None:
        return

    if get_notification_store().contains(UPDATE_NOTIFICATION_ID):
        push_update_available_toast(info)
    else:
        tag_topbar_redraw()


def push_up_to_date_toast() -> None:
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


def push_check_failed_toast() -> None:
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


def report_previous_update_result() -> None:
    """Tell the user what happened to an update we started last session.

    Called once at startup.  An install that failed after the app quit is
    otherwise completely silent: the user clicked "Restart & Update", the
    app came back, and nothing changed.
    """
    from .install_flow import read_previous_result
    from .installer import result_is_success
    from .update_checker import get_runtime_version

    try:
        result = read_previous_result()
    except Exception:  # noqa: BLE001 - startup must never fail on this
        logger.debug("Could not read the previous update result", exc_info=True)
        return

    if not result:
        return

    target = result.get("version", "")
    running = get_runtime_version() or ""

    _capture_result(result, target, running)

    if result_is_success(result):
        if target and running and target != running:
            # The installer reported success but we booted the old build:
            # on Windows this is what a relaunch of a stale path looks like.
            _push_update_outcome_toast(
                "error",
                "Update didn't take effect",
                f"Mixar {target} was installed but version {running} started. "
                "Reinstall from the downloads page.",
            )
            return
        _push_update_outcome_toast(
            "success",
            f"Updated to Mixar {target or running}",
            "The update was installed successfully.",
            ttl_ms=8000,
        )
        return

    _push_update_outcome_toast(
        "error",
        "Update was not installed",
        f"{_failure_reason(result)} You can download {target or 'the update'} "
        "from the downloads page.",
    )


def _capture_result(result, target, running) -> None:
    """Close the update funnel: what actually happened on the user's machine."""
    from .installer import result_is_success

    if result_is_success(result):
        outcome = "success"
        if target and running and target != running:
            outcome = "no_effect"
    else:
        outcome = "failed"

    try:
        from ...analytics.update_events import capture_update_result

        capture_update_result(target, outcome, result.get("stage", ""))
    except Exception:  # noqa: BLE001 - telemetry is fail-open
        logger.debug("Update result telemetry failed", exc_info=True)


def _failure_reason(result) -> str:
    """One human sentence for a helper failure record."""
    stage = result.get("stage", "")
    code = result.get("exit", "")
    if stage == "wait":
        return "Mixar was still running when the installer tried to start."
    if stage == "verify":
        return "The downloaded installer failed its signature check."
    if stage in ("mount", "unpack"):
        return "The downloaded installer could not be opened."
    if stage in ("copy", "swap"):
        return "Mixar could not be replaced on disk."
    if code == "1602":
        return "The installation was cancelled."
    if code == "1603":
        return "Windows Installer reported a fatal error."
    return "The installer did not finish."


def _push_update_outcome_toast(type_str, title, body, ttl_ms=0) -> None:
    from ...notifications.store import NotificationAction, get_notification_store
    from ..constants import UPDATE_NOTIFICATION_ID

    actions = None
    if type_str == "error":
        actions = [NotificationAction(
            label="Download", operator="mixar.open_downloads_page", style="primary",
        )]

    get_notification_store().push(
        type_str=type_str,
        title=title,
        body=body,
        priority="normal",
        actions=actions,
        ttl_ms=ttl_ms,
        id=UPDATE_NOTIFICATION_ID,
    )
