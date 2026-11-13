# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
File Type Registration After an Elevated Install (#2079)

The MSI registers ``.mixar`` for a per-user install by running the new
launcher with ``--register`` (``RegisterMixarUser``), except when the
install runs elevated: the launcher sits in a folder the user can write, and
an administrator's process must never run a file the user could have
replaced. That install writes ``HKCU\\Software\\Mixar\\Mixar\\register_pending``
(``MixarRegisterPending``) instead, and the first start that is not
elevated runs the same registration as the user (a worker thread, a few
hundred milliseconds), then deletes the value. The registration also
repoints taskbar pins carrying Mixar's AppUserModelID at the new launcher.

Nothing here needs ``bpy``.
"""

import os
import subprocess
import threading

from mixar.config.logging_config import get_logger

from ..constants import MIXAR_REGISTRY_KEY, REGISTER_PENDING_VALUE

logger = get_logger(__name__)

_TIMEOUT_S = 60
_ELEVATION_FULL = 2


def _pending() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, MIXAR_REGISTRY_KEY) as key:
            return bool(winreg.QueryValueEx(key, REGISTER_PENDING_VALUE)[0])
    except OSError:
        return False


def _clear() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, MIXAR_REGISTRY_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, REGISTER_PENDING_VALUE)
    except OSError:
        pass


def should_register(pending, elevation_type, binary) -> bool:
    """Pure: the install left the registration to us, this process is not
    elevated (an elevated start waits for a normal one), and we know our
    executable."""
    return bool(pending) and elevation_type != _ELEVATION_FULL and bool(binary)


def maybe_register_file_type(binary) -> bool:
    """Start the pending registration for *binary* (``mixar.exe``) if due.
    Main thread, cheap: one registry read. Returns True when it started."""
    if os.name != "nt":
        return False
    from .win_msi import token_elevation_type

    try:
        elevation = token_elevation_type()
    except OSError:
        elevation = None
    if not should_register(_pending(), elevation, binary):
        return False
    threading.Thread(target=_run, args=(binary,), name="MixarRegisterFileType",
                     daemon=True).start()
    return True


def _run(binary) -> None:
    try:
        done = subprocess.run(  # noqa: S603 - our own executable, fixed arguments
            [binary, "--register"], capture_output=True, timeout=_TIMEOUT_S,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Could not register the .mixar file type: %s", e)
        return
    if done.returncode == 0:
        _clear()
        logger.info("Registered the .mixar file type for this user")
    else:
        logger.warning("Registering the .mixar file type exited %s", done.returncode)
