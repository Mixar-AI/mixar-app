# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Folder-relative path validation. The only code that joins onto a root."""

from pathlib import Path, PurePosixPath

from ..constants import (
    AUDIO_SUFFIXES,
    DOCUMENT_SUFFIXES,
    IGNORED_DIRS,
    IMAGE_SUFFIXES,
    KIND_AUDIO,
    KIND_DOCUMENT,
    KIND_IMAGE,
    KIND_MODEL,
    KIND_OTHER,
    KIND_TEXT,
    KIND_VIDEO,
    MODEL_SUFFIXES,
    TEXT_SUFFIXES,
    VIDEO_SUFFIXES,
)
from .errors import ContextFolderError

_KIND_BY_SUFFIX = {
    **{suffix: KIND_TEXT for suffix in TEXT_SUFFIXES},
    **{suffix: KIND_IMAGE for suffix in IMAGE_SUFFIXES},
    **{suffix: KIND_MODEL for suffix in MODEL_SUFFIXES},
    **{suffix: KIND_DOCUMENT for suffix in DOCUMENT_SUFFIXES},
    **{suffix: KIND_VIDEO for suffix in VIDEO_SUFFIXES},
    **{suffix: KIND_AUDIO for suffix in AUDIO_SUFFIXES},
}


def file_kind(name: str) -> str:
    return _KIND_BY_SUFFIX.get(PurePosixPath(str(name)).suffix.lower(), KIND_OTHER)


def ignored_part(part: str) -> bool:
    return part.startswith(".") or part in IGNORED_DIRS


def normalize_relative_path(value, *, allow_empty: bool = False) -> str:
    """One canonical POSIX path, or a refusal of absolute/traversal forms."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_empty:
            return ""
        raise ContextFolderError("invalid_path", "A folder-relative path is required")
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise ContextFolderError("invalid_path", "Paths must be folder-relative and use '/'")
    value = value.strip()
    if allow_empty:
        value = value.rstrip("/")
        if not value:
            return ""
    path = PurePosixPath(value)
    # "C:/x" parses as a relative POSIX path whose first part is "C:".
    if path.is_absolute() or ":" in path.parts[0]:
        raise ContextFolderError("invalid_path", "Absolute paths are not allowed")
    if any(part in ("", ".", "..") for part in path.parts):
        raise ContextFolderError("invalid_path", "Traversal is not allowed")
    if any(ignored_part(part) for part in path.parts):
        raise ContextFolderError("ignored_path", "Hidden and ignored files are not shared")
    return path.as_posix()


def resolve_in_root(root: Path, relative_path, *, allow_empty: bool = False) -> Path:
    """Resolve under ``root`` and prove no symlink escapes it."""
    relative_path = normalize_relative_path(relative_path, allow_empty=allow_empty)
    root = Path(root).resolve(strict=True)
    candidate = (root / relative_path).resolve(strict=False) if relative_path else root
    if candidate != root and root not in candidate.parents:
        raise ContextFolderError("path_escape", "That path is outside the attached folder")
    return candidate


def existing_file(root: Path, relative_path) -> Path:
    path = resolve_in_root(root, relative_path)
    if not path.is_file():
        raise ContextFolderError("not_found", "No such file in the attached folder")
    return path
