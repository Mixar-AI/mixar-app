# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Self-Install Orchestration

Platform-neutral answers to three questions:

1. *Can this copy of Mixar update itself?* (:func:`check_eligibility`)
2. *Apply the staged installer and restart.* (:func:`begin_install`)
3. *What happened to the update we started last time?*
   (:func:`consume_result`)

Everything that differs per OS lives in :mod:`win_installer` and
:mod:`mac_installer`; this module decides which to call and never touches
the UI.
"""

import os
import sys

from mixar.config.logging_config import get_logger

from ..constants import INSTALLER_EXTENSIONS, SELF_INSTALL_TYPES
from . import app_paths, staging, verify

logger = get_logger(__name__)


class Eligibility:
    """Whether a self-install is possible, and why not when it isn't."""

    __slots__ = ("ok", "reason", "location", "extension")

    def __init__(self, ok, reason="", location=None, extension=""):
        self.ok = ok
        self.reason = reason
        self.location = location
        self.extension = extension

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"Eligibility(ok={self.ok}, reason={self.reason!r})"


def _platform_key() -> str:
    from .update_checker import get_platform_key

    return get_platform_key()


def check_eligibility(update_info) -> Eligibility:
    """Can we download and apply *update_info* ourselves?

    A negative verdict is not an error — it routes the toast to the
    browser download instead, which is exactly what a Linux build, a
    read-only install, or a release published without an installer
    artifact should do.
    """
    platform = _platform_key()
    allowed = SELF_INSTALL_TYPES.get(platform)
    if not allowed:
        return Eligibility(False, "In-app updates aren't supported on this platform")

    if not update_info or not update_info.download_url:
        return Eligibility(False, "This release has no in-app installer")
    if not update_info.download_sha256:
        # Without a checksum we would be running an unverified elevated
        # installer. The browser download at least shows the user what
        # they are launching.
        return Eligibility(False, "This release was published without a checksum")

    installer_type = (update_info.installer_type or "").lower()
    if installer_type not in allowed:
        return Eligibility(
            False, f"Unsupported installer type for {platform}: {installer_type or 'none'}",
        )

    location = app_paths.get_install_location()
    if not location.writable:
        return Eligibility(False, location.reason or "This install can't be updated in place")

    return Eligibility(
        True, "", location=location, extension=INSTALLER_EXTENSIONS[installer_type],
    )


def begin_install(*, installer_path, staging_dir, version, eligibility, verified):
    """Spawn the detached helper that installs *installer_path*.

    Call this immediately before quitting: the helper waits for this
    process to exit and then applies the update.

    Args:
        verified: True when the staged installer's signature was checked
            in-app.  The helper re-checks only in that case, so an
            unsigned local build still updates.

    Returns:
        The helper's ``subprocess.Popen`` — the caller keeps it so a quit
        that never happens can kill the helper instead of leaving it
        polling for our PID.

    Raises:
        OSError / ValueError: the helper could not be prepared.  The
            caller must **not** quit — nothing has changed yet.
    """
    location = eligibility.location or app_paths.get_install_location()

    if os.name == "nt":
        from . import win_installer

        return win_installer.launch(
            installer_path=installer_path,
            staging_dir=staging_dir,
            version=version,
            relaunch_candidates=location.relaunch_candidates,
            require_signature=verified,
        )

    if sys.platform == "darwin":
        from . import mac_installer

        return mac_installer.launch(
            installer_path=installer_path,
            staging_dir=staging_dir,
            target_bundle=location.target,
            version=version,
            expected_team=verify.team_id(location.target) or "",
            require_signature=verified,
        )

    raise OSError("No update helper for this platform")


def consume_result(staging_dir):
    """Read and delete the previous run's helper result.

    Returns a ``{"version", "stage", "exit"}`` dict, or ``None`` when no
    update was applied since last launch.  Deleting on read is what keeps
    a one-off failure from being reported at every subsequent startup.
    """
    path = staging.result_path(staging_dir)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            raw = handle.read()
    except OSError:
        return None

    result = {}
    for line in raw.splitlines():
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            result[key] = value.strip()

    try:
        os.remove(path)
    except OSError:
        pass

    if not result:
        return None
    logger.info("Previous update helper result: %s", result)
    return result


def result_is_success(result) -> bool:
    """True when the helper reported a completed install.

    ``3010`` is Windows Installer's "succeeded, wants a reboot" — the new
    version is on disk and running, so it counts.
    """
    if not result or result.get("stage") != "install":
        return False
    return result.get("exit") in ("0", "3010")
