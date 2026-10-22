# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Self-Install Orchestration

Platform-neutral answers to three questions:

1. *Can this copy of Mixar update itself?* (:func:`check_eligibility`)
2. *Apply the staged installer and restart.* (:func:`begin_install`)
3. *What happened to the update we started last time?*
   (:func:`consume_result`, then :func:`classify_result`)

Everything that differs per OS lives in :mod:`win_installer` and
:mod:`mac_installer`; this module decides which to call and never touches
the UI.
"""

import ntpath
import os
import sys

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_, rpt_

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
        return Eligibility(False, n_("In-app updates aren't supported on this platform"))

    if not update_info or not update_info.download_url:
        return Eligibility(False, n_("This release has no in-app installer"))
    if not update_info.download_sha256:
        # Without a checksum we would be running an unverified elevated
        # installer. The browser download at least shows the user what
        # they are launching.
        return Eligibility(False, n_("This release was published without a checksum"))

    installer_type = (update_info.installer_type or "").lower()
    if installer_type not in allowed:
        return Eligibility(
            False, rpt_("Unsupported installer type for {platform}: {installer_type}").format(
                platform=platform, installer_type=installer_type or "none"),
        )

    location = app_paths.get_install_location()
    if not location.writable:
        return Eligibility(False, location.reason or n_("This install can't be updated in place"))

    return Eligibility(
        True, "", location=location, extension=INSTALLER_EXTENSIONS[installer_type],
    )


def begin_install(
    *, installer_path, staging_dir, version, eligibility, verified,
    signer_thumbprint="", from_version="", attempt_id="",
):
    """Spawn the detached helper that installs *installer_path*.

    Call this immediately before quitting: the helper waits for this
    process to exit and then applies the update.

    Args:
        verified: True when the staged installer's signature was checked
            in-app.  The helper re-checks only in that case, so an
            unsigned local build still updates.
        signer_thumbprint: the certificate that check accepted (Windows);
            the helper's re-check requires exactly it.
        from_version / attempt_id: echoed into the helper's result file so
            the next launch can report which attempt it was (Windows).

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
            signer_thumbprint=signer_thumbprint,
            install_dir=location.target,
            from_version=from_version,
            attempt_id=attempt_id,
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
        # Windows PowerShell 5.1's Add-Content -Encoding UTF8 can write a BOM
        # where it starts appending after cmd's lines.
        key = key.strip().lstrip("﻿")
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


# Where the helper stopped before running an installer -> failure_reason.
_STAGE_REASONS = {"locked": "locked", "wait": "timeout", "verify": "signature"}
# Windows Installer exit codes worth telling apart; any other is msi_error.
_EXIT_REASONS = {"1602": "uac_declined", "1618": "another_install"}


def _same_version(left, right) -> bool:
    """``3.4`` equals ``3.4.0``; anything unparsable compares as text."""
    def key(value):
        parts = [int(part) for part in str(value).strip().split(".")]
        while len(parts) > 1 and parts[-1] == 0:
            parts.pop()
        return parts

    if not left or not right:
        return False
    try:
        return key(left) == key(right)
    except ValueError:
        return str(left).strip() == str(right).strip()


def classify_result(result, running_version, running_binary=""):
    """What the helper's *result* means, judged from the relaunched app.

    Returns ``{"outcome", "failure_reason", "relaunch_matched"}``:

    - ``success`` — the installer finished AND this process runs the
      target version. An unknown running version is not proof.
    - ``pending_reboot`` — 3010: Windows replaces some files only at the
      next restart (``files_pending_reboot`` when the old build is what
      came back).
    - ``no_effect`` — the installer said 0 but another version runs:
      ``msi_not_upgraded`` (the registry still lists another version),
      ``old_copy_relaunched`` (this binary is outside the registered
      install), ``running_version_unknown`` or ``unknown``.
    - ``failed`` — ``locked``, ``timeout``, ``signature``, ``uac_declined``
      (1602), ``another_install`` (1618), ``msi_error`` (1603/other), or
      the macOS stage that failed.

    ``relaunch_matched`` is None unless the helper recorded the registered
    install location (Windows helper v2+).
    """
    target = result.get("version", "")
    stage = result.get("stage", "")
    code = result.get("exit", "")
    location = result.get("install_location", "")
    installed = result.get("installed_version", "")

    relaunch_matched = None
    if location and running_binary:
        relaunch_matched = app_paths.is_within(ntpath.dirname(running_binary), location)

    def verdict(outcome, reason=""):
        return {
            "outcome": outcome, "failure_reason": reason,
            "relaunch_matched": relaunch_matched,
        }

    if stage != "install":
        return verdict("failed", _STAGE_REASONS.get(stage, stage or "unknown"))
    if code not in ("0", "3010"):
        return verdict("failed", _EXIT_REASONS.get(code, "msi_error"))

    took_effect = _same_version(running_version, target)
    if code == "3010":
        return verdict("pending_reboot", "" if took_effect else "files_pending_reboot")
    if took_effect:
        return verdict("success")
    if installed and not _same_version(installed, target):
        return verdict("no_effect", "msi_not_upgraded")
    if relaunch_matched is False:
        return verdict("no_effect", "old_copy_relaunched")
    if not running_version:
        return verdict("no_effect", "running_version_unknown")
    return verdict("no_effect", "unknown")
