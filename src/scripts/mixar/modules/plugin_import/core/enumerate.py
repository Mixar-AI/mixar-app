# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enumerate user-installed plugins inside a Blender version config dir.

Two plugin kinds are collected, both from the *user config* tree only
(so Blender's own bundled plugins — which Mixar already ships as a fork
— are never seen):

- Legacy add-ons under ``scripts/addons/`` (a ``*.py`` file or a package
  dir with ``__init__.py``).
- Extensions under ``extensions/<repo>/<pkg>/`` (a dir containing
  ``blender_manifest.toml``), across every repo dir the user has.

Pure module — no ``bpy`` import — so it is unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..constants import (
    ADDONS_SUBDIR,
    EXTENSION_MANIFEST,
    EXTENSIONS_SUBDIR,
    KIND_ADDON,
    KIND_EXTENSION,
    SCAN_SKIP_NAMES,
)


@dataclass(frozen=True)
class PluginInfo:
    """A single user-installed plugin discovered on disk.

    ``name`` is the add-on module name (legacy) or the extension package
    id — it doubles as the destination folder/file name in Mixar.
    ``path`` is the source file or directory to copy. ``source_repo`` is
    only set for extensions (the repo dir they came from, informational).
    """

    name: str
    kind: str
    path: Path
    is_dir: bool
    source_repo: str = field(default="")

    @property
    def label(self) -> str:
        """Human-friendly display label (folder name → Title Case)."""
        return self.name.replace("_", " ").strip().title() or self.name


def _skip(name: str) -> bool:
    return name in SCAN_SKIP_NAMES or name.startswith(".")


def list_addons(version_dir: Path) -> list[PluginInfo]:
    """List legacy user add-ons under ``<version_dir>/scripts/addons``."""
    addons_dir = version_dir / ADDONS_SUBDIR
    out: list[PluginInfo] = []
    try:
        entries = sorted(addons_dir.iterdir(), key=lambda p: p.name.lower())
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return out

    for entry in entries:
        if _skip(entry.name):
            continue
        if entry.is_dir():
            # A package add-on must have an __init__.py at its root.
            if not (entry / "__init__.py").is_file():
                continue
            out.append(PluginInfo(entry.name, KIND_ADDON, entry, is_dir=True))
        elif entry.suffix == ".py" and entry.stem != "__init__":
            out.append(PluginInfo(entry.stem, KIND_ADDON, entry, is_dir=False))
    return out


def list_extensions(version_dir: Path) -> list[PluginInfo]:
    """List user extensions under ``<version_dir>/extensions/<repo>/<pkg>``.

    Every repo dir is scanned (``blender_org``, ``user_default``, custom)
    — an extension the user installed from the online catalog is still a
    user plugin, not something bundled with Blender.
    """
    extensions_dir = version_dir / EXTENSIONS_SUBDIR
    out: list[PluginInfo] = []
    try:
        repos = sorted(extensions_dir.iterdir(), key=lambda p: p.name.lower())
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return out

    for repo in repos:
        if not repo.is_dir() or _skip(repo.name):
            continue
        try:
            pkgs = sorted(repo.iterdir(), key=lambda p: p.name.lower())
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        for pkg in pkgs:
            if not pkg.is_dir() or _skip(pkg.name):
                continue
            if not (pkg / EXTENSION_MANIFEST).is_file():
                continue
            out.append(
                PluginInfo(
                    pkg.name, KIND_EXTENSION, pkg, is_dir=True, source_repo=repo.name
                )
            )
    return out


def list_user_plugins(version_dir: Path) -> list[PluginInfo]:
    """All user-installed add-ons + extensions in ``version_dir``.

    Sorted extensions-first then add-ons, each group alphabetical, for a
    stable checklist order.
    """
    extensions = list_extensions(version_dir)
    addons = list_addons(version_dir)
    return extensions + addons
