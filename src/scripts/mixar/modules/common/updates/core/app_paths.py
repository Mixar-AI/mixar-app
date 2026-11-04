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

import ntpath
import os
import re
import sys

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_, rpt_

logger = get_logger(__name__)

# macOS Gatekeeper runs an unmoved, quarantined app from a read-only
# disk image under this path. Writing there is pointless — the changes
# vanish with the mount — so a translocated app is never self-updated.
_TRANSLOCATION_MARKER = "/AppTranslocation/"

_WINDOWS_LAUNCHERS = ("mixar-launcher.exe", "mixar.exe", "blender-launcher.exe")

# The MSI's ``Product/@Name`` (CMake ``project(Mixar)``), which Windows
# Installer writes as the Uninstall key's ``DisplayName``.
_MSI_DISPLAY_NAME = "Mixar"
_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


class InstallLocation:
    """Where the running app lives and whether we can replace it.

    ``target`` is the thing the updater replaces: the ``.app`` bundle on
    macOS, the install directory on Windows.  ``relaunch_candidates`` is
    tried in order after the update — the first that exists wins, so a
    Windows install that moves to a new directory still comes back up.
    """

    __slots__ = ("target", "writable", "reason", "relaunch_candidates", "kind")

    def __init__(self, target, writable, reason="", relaunch_candidates=(), kind=""):
        self.target = target
        self.writable = writable
        self.reason = reason
        self.relaunch_candidates = list(relaunch_candidates)
        # Windows: "msi" (the copy Windows Installer registered), "portable"
        # (any other copy) or "unknown" (the registry could not be read).
        self.kind = kind

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
            n_("Move Mixar to your Applications folder to update in place"),
        )

    bundle = _macos_bundle(binary)
    if not bundle:
        return InstallLocation(
            "", False,
            n_("Mixar is not running from an application bundle"),
        )

    parent = os.path.dirname(bundle)
    # The bundle is replaced by swapping directory entries, so it is the
    # *parent* that must be writable — a read-only bundle owned by us is
    # fine, one inside a locked /Applications is not.
    if not os.access(parent, os.W_OK | os.X_OK):
        return InstallLocation(
            bundle, False,
            rpt_("No permission to update {path}").format(path=parent),
        )

    return InstallLocation(bundle, True, "", relaunch_candidates=[bundle])


# ============================================================================
# Windows
# ============================================================================


def _default_windows_dir() -> str:
    program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
    return ntpath.join(program_files, "Mixar")


def windows_system_dir() -> str:
    """``%SystemRoot%\\System32``, where every tool the updater runs lives.

    The updater names them by absolute path: a bare name is looked up in
    the current directory first, and the staging directory a helper runs
    in is one any local account can write to. The helper's PID wait pipes
    two of them unquoted (a quoted command on each side of a cmd pipe is
    fragile), so a SystemRoot that would need quoting falls back to the
    default.
    """
    root = os.environ.get("SystemRoot") or ""
    if not re.fullmatch(r"[A-Za-z]:\\[A-Za-z0-9_.\\-]*", root):
        root = r"C:\Windows"
    return ntpath.join(root, "System32")


def _windows_relaunch_candidates(install_dir: str) -> list:
    """Executables to try after the MSI finishes, best first.

    The installed location can legitimately change across an upgrade (an
    older build installed into a version-stamped directory), so the
    current directory is tried first and the current default second.
    """
    candidates = []
    for name in _WINDOWS_LAUNCHERS:
        candidates.append(os.path.join(install_dir, name))

    default_dir = _default_windows_dir()
    if os.path.normcase(default_dir) != os.path.normcase(install_dir):
        for name in _WINDOWS_LAUNCHERS:
            candidates.append(os.path.join(default_dir, name))
    return candidates


def is_within(path: str, root: str) -> bool:
    """True when Windows *path* is *root* or inside it (case-insensitive)."""
    if not path or not root:
        return False
    path = ntpath.normcase(ntpath.normpath(path))
    root = ntpath.normcase(ntpath.normpath(root)).rstrip("\\")
    return path == root or path.startswith(root + "\\")


def windows_msi_installs() -> list:
    """Every Windows Installer registration of Mixar on this machine.

    Returns ``[{"version", "location"}]``; ``location`` is empty for MSIs
    built before ``ARPINSTALLLOCATION`` was set. Raises ``OSError`` when
    the registry cannot be read at all.
    """
    import winreg

    views = (
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    )
    installs, seen = [], set()
    for hive, view in views:
        try:
            root = winreg.OpenKey(hive, _UNINSTALL_KEY, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                if name in seen:
                    continue
                values = {}
                try:
                    with winreg.OpenKey(root, name) as key:
                        for field in ("DisplayName", "WindowsInstaller",
                                      "DisplayVersion", "InstallLocation"):
                            try:
                                values[field] = winreg.QueryValueEx(key, field)[0]
                            except OSError:
                                pass
                except OSError:
                    continue
                if values.get("DisplayName") != _MSI_DISPLAY_NAME:
                    continue
                if values.get("WindowsInstaller") != 1:
                    continue
                seen.add(name)
                installs.append({
                    "version": str(values.get("DisplayVersion") or ""),
                    "location": str(values.get("InstallLocation") or ""),
                })
    return installs


def classify_windows_install(install_dir: str, installs, default_dir: str):
    """``(kind, registered_location)`` for a copy running from *install_dir*.

    Only the copy Windows Installer registered may self-update: the MSI
    upgrades *that* copy, so a portable/zip/custom copy that installs the
    MSI would relaunch itself, unchanged. MSIs that predate
    ``ARPINSTALLLOCATION`` register no location; then only the default
    install directory counts.
    """
    if not installs:
        return "portable", ""
    located = [item["location"] for item in installs if item.get("location")]
    for location in located:
        if is_within(install_dir, location):
            return "msi", location
    if not located and is_within(install_dir, default_dir):
        return "msi", default_dir
    return "portable", ""


def _windows_location() -> InstallLocation:
    install_dir = os.path.dirname(os.path.abspath(_binary_path()))
    if not install_dir:
        return InstallLocation("", False, n_("Install directory could not be resolved"))

    try:
        kind, _registered = classify_windows_install(
            install_dir, windows_msi_installs(), _default_windows_dir(),
        )
    except Exception as e:  # noqa: BLE001 - fall back to the pre-registry behaviour
        logger.warning("Could not read the Mixar MSI registration: %s", e)
        kind = "unknown"
    if kind == "portable":
        return InstallLocation(
            install_dir, False,
            n_("This copy of Mixar wasn't installed by the Mixar installer"),
            kind=kind,
        )

    # Deliberately no write check: a per-machine MSI is *expected* to live
    # in a directory the user cannot write, and msiexec supplies the
    # elevation. Testing os.access here would refuse every normal install.
    return InstallLocation(
        install_dir, True, "",
        relaunch_candidates=_windows_relaunch_candidates(install_dir),
        kind=kind,
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
        return InstallLocation("", False, n_("Install location could not be resolved"))

    return InstallLocation(
        "", False, n_("In-app updates are not supported on this platform"),
    )
