# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
"Open with" After the Move Out of Program Files (#2079)

What a user picked in Explorer's "Open with" for a ``.mixar`` file outlives
the move: an ``Applications\\mixar-launcher.exe`` entry in the user's
classes, and the ProgID the hash-protected ``UserChoice`` names (a release
before #2079 registered ``mixar.X.Y`` for all users, with its open command
in Program Files, and the installer removes that once the folder is empty).
Double-clicking a project would then run a launcher that is gone.

Run with the shortcut repair (worker thread, once per move), this rewrites
in the user's own classes only:

- ``Applications\\<launcher>\\shell\\open\\command`` whose command runs a
  launcher in the old folder: the same command in the new folder;
- the ``mixar.*`` ProgID ``UserChoice`` names, when its open command as the
  user sees it (theirs over the machine's) runs the old folder or is gone:
  a per-user ProgID that opens the new launcher.

``UserChoice`` itself is never written (Windows checks its hash). The
registry access goes through :data:`_registry`, which tests replace.
"""

import ntpath
import os
import re

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_LAUNCHERS = ("mixar-launcher.exe", "mixar.exe", "blender-launcher.exe")
_USER_CLASSES = "Software\\Classes"
_USER_CHOICE = ("Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\"
                ".mixar\\UserChoice")


class _Registry:
    """The few winreg calls this needs (Windows only)."""

    def read(self, root, key, name=""):
        import winreg

        hive = {"HKCU": winreg.HKEY_CURRENT_USER, "HKCR": winreg.HKEY_CLASSES_ROOT}[root]
        try:
            with winreg.OpenKey(hive, key) as handle:
                value = winreg.QueryValueEx(handle, name or None)[0]
        except OSError:
            return None
        return value if isinstance(value, str) else None

    def write(self, key, value, name=""):
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, name or None, 0, winreg.REG_SZ, value)


_registry = _Registry()


def runs_from(command, folder) -> bool:
    """Pure: does *command* start a program directly in *folder*?"""
    folder = ntpath.normcase(folder.rstrip("\\/")) + "\\"
    return folder in ntpath.normcase(str(command or ""))


def moved_command(command, old_dir, new_dir) -> str:
    """Pure: *command* with every *old_dir* path pointing into *new_dir*."""
    old = re.escape(old_dir.rstrip("\\/") + "\\")
    new = new_dir.rstrip("\\/") + "\\"
    return re.sub(old, lambda _match: new, command, flags=re.IGNORECASE)


def repair_open_with(old_dir, new_dir) -> int:
    """Rewrite the user's "Open with" entries; returns how many changed."""
    if os.name != "nt" or not old_dir or not new_dir:
        return 0
    changed = 0
    for name in _LAUNCHERS:
        key = f"{_USER_CLASSES}\\Applications\\{name}\\shell\\open\\command"
        command = _registry.read("HKCU", key)
        if command and runs_from(command, old_dir):
            _registry.write(key, moved_command(command, old_dir, new_dir))
            changed += 1

    prog_id = _registry.read("HKCU", _USER_CHOICE, "ProgId") or ""
    if prog_id.lower().startswith("mixar."):
        command = _registry.read("HKCR", f"{prog_id}\\shell\\open\\command")
        launcher = ntpath.join(new_dir, "mixar-launcher.exe")
        if not command or runs_from(command, old_dir):
            base = f"{_USER_CLASSES}\\{prog_id}"
            _registry.write(f"{base}\\shell\\open\\command", f'"{launcher}" "%1"')
            _registry.write(f"{base}\\DefaultIcon", f'"{launcher}", 1')
            changed += 1
    if changed:
        logger.info("Repointed %d Open with entr%s after the move", changed,
                    "y" if changed == 1 else "ies")
        _notify_association_change()
    return changed


def _notify_association_change() -> None:
    try:
        import ctypes

        # SHCNE_ASSOCCHANGED, SHCNF_IDLIST: Explorer re-reads associations.
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:  # noqa: BLE001 - Explorer catches up on its own
        logger.debug("SHChangeNotify failed", exc_info=True)
