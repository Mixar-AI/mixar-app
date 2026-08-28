# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Install links that can actually be created on every supported platform.

Creating a symbolic link on Windows needs SeCreateSymbolicLinkPrivilege,
which a standard account only holds once Developer Mode is on — so a plain
``os.symlink`` fails with WinError 1314 on a stock machine and no add-on the
agent writes ever becomes live. A *directory junction* needs no privilege,
is read through like a real directory, and keeps the add-on live-editable
(Blender loads the project's own sources), unlike a copy.

A junction is not a symlink to Python: ``Path.is_symlink()`` is False for
one, so every ownership probe goes through :func:`is_link` here rather than
testing for a symlink directly.
"""

import os
import stat
from pathlib import Path

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def is_link(path: Path) -> bool:
    """True when the path is a symlink, or (Windows) a junction."""
    try:
        if path.is_symlink():
            return True
        if os.name != "nt":
            return False
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & _REPARSE_POINT)
    except (OSError, ValueError):
        return False


def resolves_to(target: Path, source: Path) -> bool:
    """True when both paths resolve to the same file. Never raises."""
    try:
        return Path(os.path.realpath(target)) == Path(os.path.realpath(source))
    except OSError:
        return False


def create_link(source: Path, target: Path, *, is_package: bool) -> None:
    """Link ``target`` to ``source``, raising OSError when no kind works."""
    try:
        os.symlink(source, target, target_is_directory=is_package)
        return
    except OSError:
        if os.name != "nt" or not is_package:
            # A single-module add-on has no privilege-free Windows
            # equivalent: a hard link keeps the pre-edit content after an
            # atomic write, and a copy is not the project's live source.
            raise
    try:
        import _winapi

        _winapi.CreateJunction(str(source), str(target))
    except ImportError as exc:
        raise OSError("Directory junctions are unavailable") from exc
