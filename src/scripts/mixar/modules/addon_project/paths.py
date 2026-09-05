# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Project path validation. No caller outside this module needs the root."""

import os
from pathlib import Path, PurePosixPath

from .constants import (
    EDITABLE_SUFFIXES,
    IGNORED_PARTS,
    MAX_FILE_BYTES,
    MAX_PROJECT_FILES,
)
from .errors import AddonProjectError


def normalize_relative_path(value: str) -> str:
    """Return one canonical POSIX path or reject traversal/absolute forms."""
    if not isinstance(value, str) or not value.strip():
        raise AddonProjectError("invalid_path", "A non-empty relative path is required")
    if "\\" in value or "\x00" in value:
        raise AddonProjectError("invalid_path", "Paths must use project-relative '/' separators")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise AddonProjectError("invalid_path", "Absolute paths and traversal are not allowed")
    if any(part in IGNORED_PARTS for part in path.parts):
        raise AddonProjectError("ignored_path", "That path is outside the editable project surface")
    return path.as_posix()


def resolve_project_path(root: Path, relative_path: str, *, editable=True) -> Path:
    """Resolve a relative path and prove symlinks cannot escape the root."""
    relative_path = normalize_relative_path(relative_path)
    root = root.resolve(strict=True)
    candidate = (root / relative_path).resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise AddonProjectError("path_escape", "The path resolves outside the linked project")
    if editable and candidate.suffix.lower() not in EDITABLE_SUFFIXES:
        raise AddonProjectError("unsupported_file", "Only add-on source and text files are editable")
    return candidate


def iter_project_files(root: Path):
    """Yield safe editable files without following ignored directories/symlinks."""
    root = root.resolve(strict=True)
    count = 0
    for current_value, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_value)
        directory_names[:] = sorted(
            name for name in directory_names
            if name not in IGNORED_PARTS and not (current / name).is_symlink()
        )
        for name in sorted(file_names):
            candidate = current / name
            if candidate.suffix.lower() not in EDITABLE_SUFFIXES:
                continue
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                resolved = candidate.resolve(strict=True)
                if (
                    root not in resolved.parents
                    or resolved.stat().st_size > MAX_FILE_BYTES
                ):
                    continue
            except OSError:
                continue
            count += 1
            if count > MAX_PROJECT_FILES:
                raise AddonProjectError(
                    "project_too_large",
                    f"At most {MAX_PROJECT_FILES} editable project files are supported",
                )
            yield candidate.relative_to(root).as_posix(), resolved
