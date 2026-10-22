# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Previous Update Result

Read once at startup: what the update helper recorded about the attempt
the last session started, classified by :func:`installer.classify_result`,
shown as one toast with advice for its cause, and reported as
``update.install_result``.
"""

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_, rpt_

from .toasts import _push_update_outcome_toast

logger = get_logger(__name__)


def _running_binary() -> str:
    try:
        from .app_paths import _binary_path

        return _binary_path()
    except Exception:  # noqa: BLE001 - diagnostics only
        return ""


def report_previous_update_result() -> None:
    """Tell the user what happened to an update we started last session.

    Called once at startup.  An install that failed after the app quit is
    otherwise completely silent: the user clicked "Restart & Update", the
    app came back, and nothing changed.
    """
    from .install_flow import read_previous_result
    from .installer import classify_result
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
    verdict = classify_result(result, running, _running_binary())
    outcome, reason = verdict["outcome"], verdict["failure_reason"]

    _capture_result(result, verdict, running)

    if outcome == "success":
        _push_update_outcome_toast(
            "success",
            rpt_("Updated to Mixar {version}").format(version=target or running),
            n_("The update was installed successfully."),
            ttl_ms=8000,
        )
        return

    if outcome == "pending_reboot":
        if reason:
            body = rpt_("Windows will finish installing Mixar {version} when you "
                        "restart your computer.").format(version=target)
        else:
            body = rpt_("Mixar {version} is installed. Windows replaces some of its "
                        "files only after a restart.").format(version=target)
        _push_update_outcome_toast(
            "warning", n_("Restart Windows to finish updating"), body,
        )
        return

    if outcome == "no_effect":
        _push_update_outcome_toast(
            "error", n_("Update didn't take effect"),
            _no_effect_reason(reason, result, running),
        )
        return

    if target:
        body = rpt_("{reason} You can download {version} from the downloads page.").format(
            reason=_failure_reason(result, reason), version=target)
    else:
        body = rpt_("{reason} You can download the update from the downloads page.").format(
            reason=_failure_reason(result, reason))
    _push_update_outcome_toast("error", n_("Update was not installed"), body)


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _basenames(value) -> str:
    """The helper's ``locks=`` line, re-sanitised: basenames, commas only."""
    names = []
    for name in str(value or "").split(","):
        name = "".join(ch for ch in name if ch.isalnum() or ch in "._-")
        if name and name not in names:
            names.append(name)
    return ",".join(names)


def _install_kind() -> str:
    try:
        from .app_paths import get_install_location

        return get_install_location().kind or ""
    except Exception:  # noqa: BLE001 - diagnostics only
        return ""


def _capture_result(result, verdict, running) -> None:
    """Close the update funnel: what actually happened on the user's machine.

    Versions, enums, numbers and basenames only; the helper's paths
    (``install_location``, ``relaunch``) never leave the machine.
    """
    relaunch_kind = result.get("relaunch_kind", "")
    details = {
        "from_version": result.get("from_version") or None,
        "running_version": running or None,
        "exit_code": _as_int(result.get("exit")),
        "msi_error": _as_int(result.get("msi_error")),
        "failure_reason": verdict["failure_reason"] or None,
        "attempt_id": result.get("attempt_id") or None,
        # Results without the field come from the v1 helper.
        "helper_version": _as_int(result.get("helper_version")) or 1,
        "install_kind": _install_kind() or None,
        "installed_version": result.get("installed_version") or None,
        "relaunch_matched": verdict["relaunch_matched"],
        "relaunch_kind": relaunch_kind if relaunch_kind in (
            "registry", "candidate", "fallback", "none") else None,
        "locking_processes": _basenames(result.get("locks")) or None,
        "wait_s": _as_int(result.get("wait_s")),
    }
    try:
        from ...analytics.update_events import capture_update_result

        capture_update_result(
            result.get("version", ""), verdict["outcome"], result.get("stage", ""),
            details=details,
        )
    except Exception:  # noqa: BLE001 - telemetry is fail-open
        logger.debug("Update result telemetry failed", exc_info=True)


def _no_effect_reason(reason, result, running) -> str:
    """The installer said it finished, yet another build is running."""
    target = result.get("version", "")
    if reason == "msi_not_upgraded":
        return rpt_("Windows still lists Mixar {installed} as installed. Download "
                    "{target} from the downloads page and run the installer.").format(
            installed=result.get("installed_version", ""), target=target)
    if reason == "old_copy_relaunched":
        return rpt_("Mixar {target} was installed, but this copy ({running}) runs from "
                    "another folder. Open Mixar from the Start menu instead.").format(
            target=target, running=running or "?")
    if not running:
        return rpt_("Mixar {target} was installed, but the running version could not "
                    "be confirmed.").format(target=target)
    return rpt_("Mixar {target} was installed but version {running} started. "
                "Reinstall from the downloads page.").format(target=target, running=running)


def _failure_reason(result, reason="") -> str:
    """One human sentence, with what to do, for a helper failure record."""
    stage = result.get("stage", "")
    if reason == "locked":
        names = _basenames(result.get("locks")).replace(",", ", ")
        return rpt_("Other programs were still using Mixar's files ({names}). Close "
                    "other Mixar windows and any AI app using the Mixar connector, "
                    "then try again.").format(names=names or "?")
    if stage == "wait":
        return rpt_("Mixar was still running when the installer tried to start.")
    if stage == "verify":
        return rpt_("The downloaded installer failed its signature check.")
    if stage in ("mount", "unpack"):
        return rpt_("The downloaded installer could not be opened.")
    if stage in ("copy", "swap"):
        return rpt_("Mixar could not be replaced on disk.")
    if reason == "uac_declined":
        return rpt_("The installation was cancelled at the administrator prompt. "
                    "Choose Yes when Windows asks, to install the update.")
    if reason == "another_install":
        return rpt_("Another installation was in progress. Wait for it to finish or "
                    "restart Windows, then try again.")
    if stage == "install":
        code = result.get("msi_error") or result.get("exit", "")
        return rpt_("Windows Installer reported error {code}. Restart Windows, then "
                    "try again.").format(code=code or "?")
    return rpt_("The installer did not finish.")
