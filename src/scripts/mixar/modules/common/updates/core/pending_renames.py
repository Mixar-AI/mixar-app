# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Files Windows Replaces at the Next Reboot

When an MSI exits 3010, Windows Installer could not finish every file.
It either moved a held file aside (the new one is in place; the old copy
is deleted at reboot from Windows Installer's ``Config.Msi`` folder) or,
when the holder refused delete sharing (an antivirus scanning a DLL),
wrote the new file under a temporary name and queued a rename over the
old one. In the second case the relaunched app reports the new version
while it runs the new exe against the old DLL.

Both are queued in ``PendingFileRenameOperations``; only a rename whose
destination is in the install directory means the update is not finished
until Windows restarts (a delete is clean-up). One small registry read, Windows only, no subprocess.
"""

import os
import re

from mixar.config.logging_config import get_logger

from .app_paths import is_within

logger = get_logger(__name__)

_SESSION_MANAGER_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager"
# Session Manager processes both values at boot.
_PENDING_VALUES = ("PendingFileRenameOperations", "PendingFileRenameOperations2")


def _win32_path(nt_path: str) -> str:
    """``*1\\??\\C:\\x`` / ``!\\??\\C:\\x`` -> ``C:\\x``.

    Windows writes the entries with a ``*<n>`` flag prefix (seen as ``*1`` on
    Windows Server 2022 for Windows Installer's reboot replacements) and
    ``!`` for "replace existing"; both are dropped.
    """
    path = re.sub(r"^(?:\*\d+|!)+", "", str(nt_path or "").strip())
    for prefix in ("\\??\\", "\\\\?\\", "\\\\.\\"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    if path[:4].upper() == "UNC\\":
        path = "\\\\" + path[4:]
    return path


def parse_pending_renames(values) -> list:
    """``REG_MULTI_SZ`` source/destination pairs -> ``[(source, dest)]``.

    Paths come back in Win32 form; an empty destination means delete. A
    trailing source with no destination is a delete too, and a pair with
    no source is skipped.
    """
    items = [str(value) for value in values or ()]
    if len(items) % 2:
        items.append("")
    pairs = []
    for index in range(0, len(items), 2):
        source = _win32_path(items[index])
        if source:
            pairs.append((source, _win32_path(items[index + 1])))
    return pairs


def touches(pairs, location: str) -> bool:
    """True when a reboot will move a file INTO *location*.

    Only a destination counts: that is a new file Windows still has to put
    in place. A delete (empty destination) only cleans up a moved-aside old
    copy, wherever Windows Installer put it, and leaves the update complete.
    """
    return any(dest and is_within(dest, location) for _source, dest in pairs)


def read_pending_renames() -> list:
    """Every queued ``(source, dest)`` pair. Raises ``OSError`` if unreadable."""
    import winreg

    values = []
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE, _SESSION_MANAGER_KEY, 0, winreg.KEY_QUERY_VALUE,
    ) as key:
        for name in _PENDING_VALUES:
            try:
                data, _kind = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                continue  # nothing queued
            if isinstance(data, (list, tuple)):
                values.extend(parse_pending_renames(data))
    return values


def _on_windows() -> bool:
    return os.name == "nt"


def files_pending_reboot(location: str) -> bool:
    """Does Windows still have to replace files under *location* at reboot?

    False off Windows, without a location, or when the registry cannot be
    read (logged): the caller then keeps its verdict from the version.
    """
    if not location or not _on_windows():
        return False
    try:
        pairs = read_pending_renames()
    except OSError as e:
        logger.warning("Could not read pending file renames: %s", e)
        return False
    pending = touches(pairs, location)
    logger.info("Pending file renames under the install directory: %s", pending)
    return pending
