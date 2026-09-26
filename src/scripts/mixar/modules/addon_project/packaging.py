# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build a shareable zip of one add-on for Mixar Community.

Pure Python (no bpy) so the standalone suite covers it. The zip holds exactly
one top-level package, ``<entrypoint>/...``, which is the layout Blender's
Install from Disk and the community server both expect. Nothing that
identifies the machine goes in: entry names are package-relative, timestamps
are fixed, and project metadata (``.mixar``) and caches are excluded.
"""

import ast
import io
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .constants import IGNORED_PARTS
from .errors import AddonProjectError

MAX_PACKAGE_FILES = 2000
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
# Mirrors the community server's refusal list; failing here gives the author
# the reason before an upload rather than after it.
REFUSED_SUFFIXES = frozenset({
    ".so", ".pyd", ".dll", ".dylib", ".exe", ".bat", ".sh", ".command", ".pyc", ".pyo",
})
_FIXED_TIME = (2026, 1, 1, 0, 0, 0)


@dataclass
class PackagedAddon:
    filename: str
    data: bytes
    package: str
    file_count: int
    bl_info: dict = field(default_factory=dict)

    @property
    def title(self) -> str:
        return str(self.bl_info.get("name") or self.package.replace("_", " ").title())

    @property
    def description(self) -> str:
        return str(self.bl_info.get("description") or "")


def read_bl_info(source: str) -> dict:
    """Return the literal ``bl_info`` dict without importing the module."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "bl_info" for t in node.targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return {}
            return value if isinstance(value, dict) else {}
    return {}


def _package_source(root: Path, entrypoint: str):
    """Return (directory or None, single-file module or None) for the add-on."""
    package_dir = root / entrypoint
    if package_dir.is_dir() and not package_dir.is_symlink():
        return package_dir, None
    if root.name == entrypoint and (root / "__init__.py").is_file():
        return root, None  # standalone project whose root is the package
    module = root / f"{entrypoint}.py"
    if module.is_file() and not module.is_symlink():
        return None, module
    raise AddonProjectError("entrypoint_missing", f"Can't find the add-on '{entrypoint}' to publish")


def _iter_package_files(package_dir: Path):
    for current, dirs, files in os.walk(package_dir, topdown=True, followlinks=False):
        here = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_PARTS and not (here / d).is_symlink())
        for name in sorted(files):
            path = here / name
            if path.is_symlink() or not path.is_file():
                continue
            yield path.relative_to(package_dir).as_posix(), path


def build_addon_zip(root: Path, entrypoint: str) -> PackagedAddon:
    if not entrypoint or not entrypoint.isidentifier():
        raise AddonProjectError("invalid_entrypoint", "Pick an add-on to publish first")
    root = Path(root)
    package_dir, module = _package_source(root, entrypoint)
    entries = [("__init__.py", module)] if module else list(_iter_package_files(package_dir))
    if not any(rel == "__init__.py" for rel, _ in entries):
        raise AddonProjectError("entrypoint_missing", f"{entrypoint}/__init__.py is missing")
    if len(entries) > MAX_PACKAGE_FILES:
        raise AddonProjectError("project_too_large", f"Add-ons are limited to {MAX_PACKAGE_FILES} files")

    buffer = io.BytesIO()
    total = 0
    bl_info = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel, path in entries:
            if path.suffix.lower() in REFUSED_SUFFIXES:
                if path.suffix.lower() in (".pyc", ".pyo"):
                    continue
                raise AddonProjectError(
                    "unsupported_file",
                    f"{rel} is a native binary or shell script; Mixar Community only accepts Python add-ons",
                )
            data = path.read_bytes()
            total += len(data)
            if total > MAX_PACKAGE_BYTES:
                raise AddonProjectError("project_too_large", "Add-ons are limited to 50 MB")
            if rel == "__init__.py":
                bl_info = read_bl_info(data.decode("utf-8", errors="replace"))
            info = zipfile.ZipInfo(f"{entrypoint}/{rel}", date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)

    if not bl_info.get("name"):
        raise AddonProjectError(
            "bl_info_missing",
            "Add a bl_info dict with a 'name' to the add-on's __init__.py before publishing",
        )
    return PackagedAddon(
        filename=f"{entrypoint}.zip",
        data=buffer.getvalue(),
        package=entrypoint,
        file_count=len(entries),
        bl_info=bl_info,
    )
