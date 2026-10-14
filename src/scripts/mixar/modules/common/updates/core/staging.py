# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update Staging Directory

Where the downloaded installer lives until it is applied.  Pure path and
filesystem work — imports no ``bpy`` and is safe to call from the
download thread.

**Why this module exists.**  The first native-restart implementation
staged the installer in the per-user temp directory
(``%LOCALAPPDATA%\\Temp\\mixar_updates``) and Windows installs failed
there.  A per-machine MSI must run elevated, and when the signed-in user
is a *standard* user the UAC prompt is satisfied by a **different**
account — ``msiexec`` then runs as that admin and cannot read a file
inside the original user's profile, so the install dies with "This
installation package could not be opened" before it starts.  The same
happens under some endpoint-protection policies that block execution out
of ``%TEMP%``.

So the installer is staged under ``%ProgramData%`` instead: readable by
every account on the machine, writable by us (the directory we create is
owned by the creating user), and outside both the app directory the MSI
replaces and the temp directories AV products police.  The per-user
directory remains as a fallback, but the caller is told when the shared
location was unavailable so it can warn instead of failing at the UAC
prompt.
"""

import os
import shutil
import subprocess
import sys
import tempfile

from mixar.config.logging_config import get_logger

from ..constants import (
    HELPER_RESULT_NAME,
    PARTIAL_SUFFIX,
    STAGING_DIR_NAME,
    STAGING_VENDOR_DIR,
)

logger = get_logger(__name__)

# Resolving creates directories and, on Windows, runs icacls. Both are
# cheap once and pointless every time, and one caller is the startup path.
_resolved = None

# Well-known SIDs — language independent, unlike "Users"/"Administrators",
# which are localised and make icacls fail on non-English Windows.
_SID_USERS = "*S-1-5-32-545"
_SID_ADMINS = "*S-1-5-32-544"


class StagingDir:
    """A resolved staging directory plus whether every account can read it.

    ``shared`` is False when we had to fall back to a per-user location:
    the install still works for an admin user elevating their own session
    (by far the common case), but a standard user whose UAC prompt is
    answered with someone else's admin credentials will not be able to
    read the installer.  Callers surface that as a warning rather than
    discovering it at install time.
    """

    __slots__ = ("path", "shared")

    def __init__(self, path: str, shared: bool):
        self.path = path
        self.shared = shared

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"StagingDir(path={self.path!r}, shared={self.shared})"


# ============================================================================
# Candidate roots
# ============================================================================


def _windows_candidates() -> list:
    """(root, shared) pairs for Windows, best first."""
    candidates = []
    program_data = os.environ.get("ProgramData") or os.environ.get("ALLUSERSPROFILE")
    if program_data:
        candidates.append((program_data, True))
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append((local_appdata, False))
    candidates.append((tempfile.gettempdir(), False))
    return candidates


def _posix_candidates() -> list:
    """(root, shared) pairs for macOS/Linux, best first.

    Nothing on these platforms needs a cross-account readable location —
    the macOS updater swaps the bundle as the signed-in user — so a
    per-user directory is the *correct* home, not a fallback, and is
    reported as shared.
    """
    home = os.path.expanduser("~")
    candidates = []
    if sys.platform == "darwin":
        candidates.append((os.path.join(home, "Library", "Application Support"), True))
    else:
        xdg = os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
        candidates.append((xdg, True))
    candidates.append((tempfile.gettempdir(), True))
    return candidates


def _is_windows() -> bool:
    """Indirection so tests can exercise the Windows path on any host."""
    return os.name == "nt"


def _is_usable(path: str) -> bool:
    """Create *path* and prove we can actually write a file inside it."""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        logger.debug("Staging candidate %s not creatable: %s", path, e)
        return False

    probe = os.path.join(path, ".write_probe")
    try:
        with open(probe, "wb") as f:
            f.write(b"0")
    except OSError as e:
        logger.debug("Staging candidate %s not writable: %s", path, e)
        return False
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass
    return True


def _grant_machine_read(path: str) -> None:
    """Give every local account read access to *path* (Windows only).

    ``%ProgramData%`` already grants ``Users`` read-and-execute through
    inheritance, so this is belt and braces for machines whose ACLs were
    tightened by policy — and it costs one process.  Failure is logged and
    ignored: the inherited ACL is usually enough, and refusing to update
    because ``icacls`` is missing would be worse than trying.
    """
    if not _is_windows():
        return
    try:
        subprocess.run(
            [
                "icacls", path,
                "/grant", f"{_SID_USERS}:(OI)(CI)RX",
                "/grant", f"{_SID_ADMINS}:(OI)(CI)F",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except Exception as e:  # noqa: BLE001 - diagnostics only
        logger.debug("icacls on %s failed (continuing): %s", path, e)


# ============================================================================
# Public API
# ============================================================================


def resolve_staging_dir() -> StagingDir:
    """Return the best usable staging directory for this platform.

    Cached per process: the answer cannot change while we run, and the
    first call is on the startup path.

    Raises:
        OSError: no candidate root was writable — the caller must fall
            back to the browser download.
    """
    global _resolved
    if _resolved is not None:
        return _resolved

    windows = _is_windows()
    candidates = _windows_candidates() if windows else _posix_candidates()

    for root, shared in candidates:
        vendor = os.path.join(root, STAGING_VENDOR_DIR)
        first_run = not os.path.isdir(vendor)
        path = os.path.join(vendor, STAGING_DIR_NAME)
        if not _is_usable(path):
            continue
        # Only on creation: re-running icacls on every launch would put a
        # subprocess on the startup path for no gain.
        if shared and windows and first_run:
            _grant_machine_read(vendor)
        if not shared:
            logger.warning(
                "Staging updates in per-user directory %s — a standard user "
                "elevating with another account may not be able to read it",
                path,
            )
        _resolved = StagingDir(path, shared)
        return _resolved

    raise OSError("No writable staging directory found for updates")


def installer_path(staging: StagingDir, version: str, extension: str) -> str:
    """Full path of the staged installer for *version*."""
    return os.path.join(staging.path, f"Mixar-{version}{extension}")


def purge_stale(staging: StagingDir, keep_filenames=()) -> None:
    """Delete previously staged installers, helpers and logs.

    A 400 MB installer per release adds up, and a stale helper script from
    a cancelled attempt must never be found and run later.  Anything named
    in *keep_filenames* survives.
    """
    keep = set(keep_filenames)
    try:
        entries = os.listdir(staging.path)
    except OSError:
        return

    for name in entries:
        if name in keep:
            continue
        target = os.path.join(staging.path, name)
        try:
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            else:
                os.remove(target)
        except OSError as e:
            logger.debug("Could not purge stale update file %s: %s", target, e)


def result_path(staging_dir_path: str) -> str:
    """Where the update helper records what it did.

    Takes a plain path rather than a :class:`StagingDir` so the helper
    generators — which only ever know a directory — can share it.
    """
    return os.path.join(staging_dir_path, HELPER_RESULT_NAME)


def partial_path(final_path: str) -> str:
    """Path the download writes to before its checksum is verified."""
    return final_path + PARTIAL_SUFFIX
