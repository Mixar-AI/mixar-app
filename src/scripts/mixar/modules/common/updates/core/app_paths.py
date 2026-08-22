# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Installed-Application Paths

Answers "where is this copy of Mixar installed, and may we replace it?"
for the self-updater.  Everything is derived from ``bpy.app.binary_path``
(the running binary) rather than a guessed default, so a user who moved
the app, or runs a second build, updates the copy they actually launched.
"""

import os
import sys

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# macOS Gatekeeper runs an unmoved, quarantined app from a read-only
# disk image under this path. Writing there is pointless — the changes
# vanish with the mount — so a translocated app is never self-updated.
_TRANSLOCATION_MARKER = "/AppTranslocation/"

_WINDOWS_LAUNCHERS = ("mixar-launcher.exe", "mixar.exe", "blender-launcher.exe")


class InstallLocation:
    """Where the running app lives and whether we can replace it.

    ``target`` is the thing the updater replaces: the ``.app`` bundle on
    macOS, the install directory on Windows.  ``relaunch_candidates`` is
    tried in order after the update — the first that exists wins, so a
    Windows install that moves to a new directory still comes back up.
    """

    __slots__ = ("target", "writable", "reason", "relaunch_candidates")

    def __init__(self, target, writable, reason="", relaunch_candidates=()):
        self.target = target
        self.writable = writable
        self.reason = reason
        self.relaunch_candidates = list(relaunch_candidates)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (
            f"InstallLocation(target={self.target!r}, writable={self.writable}, "
            f"reason={self.reason!r})"
        )


def _binary_path() -> str:
    import bpy

    return bpy.app.binary_path or sys.executable


# ============================================================================
# macOS
# ============================================================================


def _macos_bundle(binary: str) -> str:
    """Walk up from the executable to the enclosing ``.app`` bundle."""
    path = os.path.abspath(binary)
    while path and path != "/":
        if path.endswith(".app") and os.path.isdir(path):
            return path
        path = os.path.dirname(path)
    return ""


def _macos_location() -> InstallLocation:
    binary = _binary_path()

    # Checked on the binary path, before resolving the bundle: a
    # translocated app runs from a synthesised read-only mount, so the
    # bundle we would find there is not the one on disk.
    if _TRANSLOCATION_MARKER in binary:
        return InstallLocation(
            "", False,
            "Move Mixar to your Applications folder to update in place",
        )

    bundle = _macos_bundle(binary)
    if not bundle:
        return InstallLocation(
            "", False,
            "Mixar is not running from an application bundle",
        )

    parent = os.path.dirname(bundle)
    # The bundle is replaced by swapping directory entries, so it is the
    # *parent* that must be writable — a read-only bundle owned by us is
    # fine, one inside a locked /Applications is not.
    if not os.access(parent, os.W_OK | os.X_OK):
        return InstallLocation(
            bundle, False,
            f"No permission to update {parent}",
        )

    return InstallLocation(bundle, True, "", relaunch_candidates=[bundle])


# ============================================================================
# Windows
# ============================================================================


def _windows_relaunch_candidates(install_dir: str) -> list:
    """Executables to try after the MSI finishes, best first.

    The installed location can legitimately change across an upgrade (an
    older build installed into a version-stamped directory), so the
    current directory is tried first and the current default second.
    """
    candidates = []
    for name in _WINDOWS_LAUNCHERS:
        candidates.append(os.path.join(install_dir, name))

    program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
    default_dir = os.path.join(program_files, "Mixar")
    if os.path.normcase(default_dir) != os.path.normcase(install_dir):
        for name in _WINDOWS_LAUNCHERS:
            candidates.append(os.path.join(default_dir, name))
    return candidates


def _windows_location() -> InstallLocation:
    install_dir = os.path.dirname(os.path.abspath(_binary_path()))
    if not install_dir:
        return InstallLocation("", False, "Install directory could not be resolved")

    # Deliberately no write check: a per-machine MSI is *expected* to live
    # in a directory the user cannot write, and msiexec supplies the
    # elevation. Testing os.access here would refuse every normal install.
    return InstallLocation(
        install_dir, True, "",
        relaunch_candidates=_windows_relaunch_candidates(install_dir),
    )


# ============================================================================
# Public API
# ============================================================================


def get_install_location() -> InstallLocation:
    """Resolve the install location of the running app for this platform."""
    try:
        if sys.platform == "darwin":
            return _macos_location()
        if os.name == "nt":
            return _windows_location()
    except Exception as e:  # noqa: BLE001 - never break the update check
        logger.error("Could not resolve install location: %s", e, exc_info=True)
        return InstallLocation("", False, "Install location could not be resolved")

    return InstallLocation(
        "", False, "In-app updates are not supported on this platform",
    )
