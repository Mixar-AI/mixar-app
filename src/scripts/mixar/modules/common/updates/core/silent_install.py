# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Installing Without Asking: the Gate, and Install on Quit

Restart & Update asks; an update staged, verified and eligible is also
installed when the user quits Mixar normally, so the next launch is the
new version. The quit itself is unchanged: no dialog, no wait, nothing
new on screen — the helper starts in ``exit_pre`` (a few milliseconds:
a process-table read, a script written, a process spawned) and installs
once Mixar has exited, then leaves it closed. A launch turned away while
it works is reopened when it is done.

:func:`silent_refusal` is the one gate every install nobody asked for
passes — on quit here, at launch in :mod:`launch_install`. It refuses
unless the installer's signature was verified in this process against a
pinned signer (``verify.VERIFIED`` with a signer: on macOS a non-empty
Team ID that is the running app's; on Windows the MSI's certificate, and
this app must itself be validly signed — :mod:`win_signer`, whose subject
the helper also requires of the MSI — so an unsigned or dev build, or one
whose signer cannot be read, never installs by itself and keeps Restart
to Update), when the install would raise an administrator prompt
(``InstallLocation.needs_elevation``: on Windows anything but a per-user
install in the user's profile), when this version already failed
``SILENT_INSTALL_MAX_FAILURES`` times, and whenever the Restart & Update
gate would stop or wait (another Mixar, background work, a program running
from the install; :func:`install_gate.silent_blocker`).

``exit_pre``'s argument tells a normal quit (True) from background mode,
a failed start or ``sys.exit`` (False). A crash, a force quit or a kill
runs no handler at all; :mod:`launch_install` covers those.
"""

import os

from mixar.config.logging_config import get_logger

from ..constants import SILENT_INSTALL_MAX_FAILURES, TRIGGER_QUIT, InstallState
from . import install_gate, install_start, installer, staged_record, win_signer
from .preferences import install_on_quit_enabled
from .state import get_update_state

logger = get_logger(__name__)


def failure_count(record) -> int:
    try:
        return max(0, int((record or {}).get("failures") or 0))
    except (TypeError, ValueError):
        return 0


def silent_refusal(eligibility, record=None, *, verified=False, signer="") -> str:
    """Why an install nobody asked for must not run now; ``""`` when it may.

    *record* is the version's :mod:`staged_record` (its failure count only:
    the file is the user's to edit, so it never vouches for a signature).
    *verified* / *signer* are this process's own verdict and pinned signer.
    """
    if not eligibility:
        return eligibility.reason or "not eligible"
    if not verified or not signer:
        return "its signature was not verified against this app's"
    if os.name == "nt":
        refusal = win_signer.silent_refusal()
        if refusal:
            return refusal
    return install_refusal(eligibility, record)


def install_refusal(eligibility, record=None) -> str:
    """:func:`silent_refusal` without the signature: what a launch can tell
    before its own signature check has run (and read this app's signer)."""
    if not eligibility:
        return eligibility.reason or "not eligible"
    location = eligibility.location
    if location is None or location.needs_elevation:
        return "the install needs an administrator prompt"
    if failure_count(record) >= SILENT_INSTALL_MAX_FAILURES:
        return "this version failed to install before"
    blocker = install_gate.silent_blocker(eligibility)
    if blocker:
        return f"in use by {blocker}"
    return ""


def install_on_quit(user_exit) -> bool:
    """``exit_pre``: start the helper for a ready update. True once started.

    Never raises and never asks: whatever happens here, the quit goes on.
    """
    try:
        return _install_on_quit(user_exit)
    except Exception:  # noqa: BLE001 - the quit must never fail on this
        logger.error("Install on quit failed; the update stays staged", exc_info=True)
        return False


def _install_on_quit(user_exit) -> bool:
    if user_exit is not True:
        return False  # background mode, a failed start-up, sys.exit
    state = get_update_state()
    # READY only (anything else has nothing ready), and never beside a
    # helper this process started: Restart & Update's quit (INSTALLING) or
    # the launch install's, which can find READY again — a Check for
    # Updates or an update notification during its wait stages the same
    # version.
    if state.install_state is not InstallState.READY or install_start.helper_started():
        return False
    if not install_on_quit_enabled():
        logger.info("Update ready; installing on quit is turned off")
        return False
    info, path = state.update_info, state.installer_path
    if info is None or not path or not os.path.isfile(path):
        return False

    record = staged_record.read(os.path.dirname(path))
    if record is not None and record.get("version") != info.latest_version:
        record = None
    eligibility = installer.check_eligibility(info)
    refusal = silent_refusal(eligibility, record, verified=state.signature_verified,
                             signer=state.signer_thumbprint)
    if refusal:
        logger.info("Not installing %s on quit: %s", info.latest_version, refusal)
        return False

    install_start.start_helper(
        installer_path=path,
        version=info.latest_version,
        eligibility=eligibility,
        verified=state.signature_verified,
        signer=state.signer_thumbprint,
        trigger=TRIGGER_QUIT,
        relaunch=False,
    )
    state.set_installing()
    return True
