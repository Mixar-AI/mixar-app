# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Installer Signature Verification

The checksum in :mod:`download` proves the bytes match what the backend
published.  This module answers the other half: that what the backend
published was signed by **the same publisher as the copy already
running**.  It is the check that makes an unattended, elevated install
defensible — a compromised release row can change the checksum it
advertises, but not the signing identity of the app the user installed.

Comparing against the running app rather than a hardcoded identity means
a certificate rotation needs no client release, and a dev/unsigned build
degrades to "checksum only" instead of refusing to update at all.

Both checks shell out to the platform tools (``Get-AuthenticodeSignature``
/ ``codesign``); a tool that cannot be run is reported as
:data:`UNVERIFIED`, never as a failure.
"""

import os
import subprocess
import sys

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

VERIFIED = "verified"
UNVERIFIED = "unverified"   # could not check — allowed, logged
REJECTED = "rejected"       # actively bad — never install

_TIMEOUT_S = 90


def _run(argv):
    """Run *argv*, returning (returncode, stdout+stderr) or None if it died."""
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=_TIMEOUT_S,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if os.name == "nt" else 0,
        )
    except Exception as e:  # noqa: BLE001 - missing tool, sandbox, timeout
        logger.debug("Signature tool %s unavailable: %s", argv[0], e)
        return None
    return completed.returncode, completed.stdout.decode("utf-8", "replace").strip()


# ============================================================================
# Windows — Authenticode
# ============================================================================

_PS_SIGNER = (
    "$ErrorActionPreference='Stop';"
    "$s=Get-AuthenticodeSignature -LiteralPath {path};"
    "Write-Output $s.Status;"
    "if($s.SignerCertificate){Write-Output $s.SignerCertificate.Subject}"
)


def _ps_quote(path):
    """Single-quote a path for PowerShell (doubling embedded quotes)."""
    return "'" + str(path).replace("'", "''") + "'"


def _authenticode(path):
    """Return (status, signer_subject) for *path*, or None if unavailable."""
    result = _run([
        "powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-Command", _PS_SIGNER.format(path=_ps_quote(path)),
    ])
    if result is None:
        return None
    code, output = result
    if code != 0:
        logger.debug("Get-AuthenticodeSignature failed (%s): %s", code, output)
        return None
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return None
    return lines[0], (lines[1] if len(lines) > 1 else "")


def _verify_windows(installer_path, running_binary):
    running = _authenticode(running_binary) if running_binary else None
    staged = _authenticode(installer_path)

    if staged is None:
        return UNVERIFIED, "Authenticode check unavailable"

    status, subject = staged
    if status != "Valid":
        if running is None or running[0] != "Valid":
            # An unsigned dev build updating to an unsigned dev installer
            # is a legitimate local workflow; only refuse when the running
            # app proves releases are supposed to be signed.
            return UNVERIFIED, f"Installer signature status: {status}"
        return REJECTED, f"Installer is not validly signed ({status})"

    if running and running[0] == "Valid" and running[1] and subject:
        if running[1] != subject:
            return REJECTED, "Installer was signed by a different publisher"

    return VERIFIED, subject


# ============================================================================
# macOS — codesign
# ============================================================================


def team_id(path):
    """Team identifier of a signed bundle or disk image, or ``""``."""
    result = _run(["codesign", "-dv", "--verbose=4", str(path)])
    if result is None:
        return None
    code, output = result
    if code != 0:
        return ""
    for line in output.splitlines():
        if line.startswith("TeamIdentifier="):
            value = line.split("=", 1)[1].strip()
            return "" if value in ("not set", "") else value
    return ""


def _verify_macos(installer_path, bundle_path):
    result = _run(["codesign", "--verify", "--strict", str(installer_path)])
    if result is None:
        return UNVERIFIED, "codesign unavailable"

    code, output = result
    running_team = team_id(bundle_path) if bundle_path else None

    if code != 0:
        if not running_team:
            # Unsigned local build — the checksum is all we have and all
            # that is warranted.
            return UNVERIFIED, "Disk image is unsigned"
        return REJECTED, f"Disk image failed signature verification: {output[:200]}"

    staged_team = team_id(installer_path)
    if running_team and staged_team and running_team != staged_team:
        return REJECTED, "Disk image was signed by a different Apple team"

    return VERIFIED, staged_team or ""


# ============================================================================
# Public API
# ============================================================================


def verify_installer(installer_path, bundle_path="", running_binary=""):
    """Check the staged installer's signature against the running app.

    Args:
        installer_path: the staged ``.msi`` / ``.dmg``.
        bundle_path: macOS ``.app`` of the running copy, for team-id
            comparison.
        running_binary: Windows executable of the running copy, for
            Authenticode publisher comparison.  Resolved by the caller —
            this module stays free of ``bpy``.

    Returns:
        ``(VERIFIED | UNVERIFIED | REJECTED, detail)``.  Only ``REJECTED``
        must block the install; ``UNVERIFIED`` means no verdict was
        available and the checksum stands alone.
    """
    try:
        if os.name == "nt":
            return _verify_windows(installer_path, running_binary)
        if sys.platform == "darwin":
            return _verify_macos(installer_path, bundle_path)
    except Exception as e:  # noqa: BLE001 - verification must never crash
        logger.error("Installer verification error: %s", e, exc_info=True)
        return UNVERIFIED, "Verification error"

    return UNVERIFIED, "No signature verification on this platform"
