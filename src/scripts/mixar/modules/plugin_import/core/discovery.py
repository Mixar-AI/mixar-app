# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Locate the user's vanilla Blender install(s) to import plugins from.

Mixar is a Blender fork that stores its own user data under ``Mixar/5.0``
(see the GHOST paths rebrand), so a normal Blender install lives beside
it under the platform's standard ``Blender/<ver>`` config tree. This
module finds those source config directories and picks the newest
version — no ``bpy`` import, so it is unit-testable outside Blender.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from ..constants import (
    LINUX_BLENDER_BASE,
    MACOS_BLENDER_BASE,
    WINDOWS_BLENDER_BASE,
)

# A Blender version config folder is exactly "<major>.<minor>".
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)$")


def blender_base_dirs(
    platform: str | None = None,
    home: Path | None = None,
    environ: dict | None = None,
) -> list[Path]:
    """Return the base dir(s) that directly contain Blender version folders.

    Args are injectable so tests can pin the platform/home/env. In normal
    use they default to the live process. The returned paths are not
    guaranteed to exist — callers filter with :func:`find_source_versions`.
    """
    platform = platform if platform is not None else sys.platform
    home = home if home is not None else Path.home()
    environ = environ if environ is not None else os.environ

    if platform == "darwin":
        return [home.joinpath(*MACOS_BLENDER_BASE)]

    if platform.startswith("win"):
        appdata = environ.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return [base.joinpath(*WINDOWS_BLENDER_BASE)]

    # Linux / other POSIX — honour XDG_CONFIG_HOME, fall back to ~/.config.
    xdg = environ.get("XDG_CONFIG_HOME")
    config_home = Path(xdg) if xdg else home / ".config"
    return [config_home / LINUX_BLENDER_BASE[-1]]


def _parse_version(name: str) -> tuple[int, int] | None:
    m = _VERSION_RE.match(name)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def find_source_versions(bases: list[Path] | None = None, **kwargs) -> list[tuple[str, Path]]:
    """Find all installed Blender version config dirs, newest first.

    Returns a list of ``(version_str, version_dir)`` sorted by version
    descending (e.g. ``("4.5", Path(".../Blender/4.5"))``). ``**kwargs``
    are forwarded to :func:`blender_base_dirs` (platform/home/environ)
    when ``bases`` is not supplied.
    """
    if bases is None:
        bases = blender_base_dirs(**kwargs)

    found: dict[tuple[int, int], Path] = {}
    for base in bases:
        try:
            entries = list(base.iterdir())
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            version = _parse_version(entry.name)
            if version is None:
                continue
            # First base wins for a duplicate version number.
            found.setdefault(version, entry)

    ordered = sorted(found.items(), key=lambda kv: kv[0], reverse=True)
    return [(f"{maj}.{minr}", path) for (maj, minr), path in ordered]


def newest_source_version(bases: list[Path] | None = None, **kwargs) -> tuple[str, Path] | None:
    """Return ``(version_str, version_dir)`` for the newest Blender install,
    or ``None`` if no vanilla Blender config dir is found."""
    versions = find_source_versions(bases=bases, **kwargs)
    return versions[0] if versions else None
