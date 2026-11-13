# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
GPU Preference After the Move Out of Program Files (#2079)

Windows keeps the GPU a user chose for a program (Settings > System >
Display > Graphics) under the program's full path:
``HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences``, one value per
``.exe`` (data such as ``GpuPreference=2;``, the high-performance GPU). After
the move the new ``mixar.exe`` has none, so a laptop would render Mixar on
its integrated GPU again.

Run with the shortcut repair (worker thread, once per move), this copies
each preference for a program directly in the old folder to its counterpart
in the new one, when that exists and has none of its own. The old values
stay: another account's copy may still be there, and Windows ignores a path
that is gone. Other settings Windows keys by a program's path are not
carried over: Controlled Folder Access, Defender exclusions and firewall
rules belong to an administrator, and compatibility settings
(``AppCompatFlags``) are rarely set for Mixar and may not suit the new copy.
"""

import ntpath
import os

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_KEY = "Software\\Microsoft\\DirectX\\UserGpuPreferences"


def moved_preferences(values, old_dir, new_dir, exists) -> dict:
    """Pure: ``{new path: data}`` for every preference in *values* (``{.exe
    path: data}``) on a program directly in *old_dir* whose counterpart in
    *new_dir* *exists* and has no preference yet."""
    old = ntpath.normcase(old_dir.rstrip("\\/"))
    taken = {ntpath.normcase(name) for name in values}
    moved = {}
    for name, data in values.items():
        folder, program = ntpath.split(name)
        if not program or ntpath.normcase(folder.rstrip("\\/")) != old:
            continue
        target = ntpath.join(new_dir.rstrip("\\/"), program)
        if ntpath.normcase(target) not in taken and exists(target):
            moved[target] = data
    return moved


def repair_gpu_preference(old_dir, new_dir) -> int:
    """Copy the old folder's GPU preferences to the new one; returns how many."""
    if os.name != "nt" or not old_dir or not new_dir:
        return 0
    moved = moved_preferences(_read_preferences(), old_dir, new_dir, _exists)
    for name, data in moved.items():
        _write_preference(name, data)
    if moved:
        logger.info("Carried the GPU preference of %d program(s) over after the move", len(moved))
    return len(moved)


def _exists(path) -> bool:
    return os.path.isfile(path)


def _read_preferences() -> dict:
    import winreg

    values = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY) as key:
            for index in range(winreg.QueryInfoKey(key)[1]):
                name, data, kind = winreg.EnumValue(key, index)
                if kind == winreg.REG_SZ and isinstance(data, str):
                    values[name] = data
    except FileNotFoundError:
        return {}
    return values


def _write_preference(name, data) -> None:
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, data)
