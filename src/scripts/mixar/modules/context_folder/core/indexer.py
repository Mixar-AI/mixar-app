# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded, symlink-safe walk of an attached folder.

Shared by the per-turn manifest (main thread, at Send) and the list/search
RPCs (worker threads). A short TTL cache keeps a burst of agent calls from
re-walking a large folder; the walk itself never follows a link out of the
root and stops at ``MAX_INDEXED_FILES`` (reported as ``truncated``).
"""

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..constants import INDEX_TTL_S, KINDS, MAX_DEPTH, MAX_INDEXED_FILES
from .errors import ContextFolderError
from .paths import file_kind, ignored_part


@dataclass
class FolderIndex:
    files: list = field(default_factory=list)  # {"path", "kind", "size", "mtime"}
    truncated: bool = False
    total_bytes: int = 0
    built_at: float = 0.0

    def counts(self) -> dict:
        counts = {kind: 0 for kind in KINDS}
        for entry in self.files:
            counts[entry["kind"]] += 1
        return {kind: count for kind, count in counts.items() if count}


_cache: dict = {}
_cache_lock = threading.Lock()


def _walk(root: Path) -> FolderIndex:
    index = FolderIndex(built_at=time.monotonic())
    root_text = str(root)

    def walk_error(error):
        if os.path.normpath(error.filename or "") == os.path.normpath(root_text):
            raise ContextFolderError("folder_unavailable", "The attached folder cannot be read") from error
        # A readable root can contain inaccessible children. Keep useful entries,
        # but never claim that a partial walk is a complete or empty listing.
        index.truncated = True

    for current, directories, names in os.walk(root, topdown=True, followlinks=False,
                                               onerror=walk_error):
        relative_dir = os.path.relpath(current, root_text)
        depth = 0 if relative_dir == "." else relative_dir.count(os.sep) + 1
        directories[:] = sorted(
            name for name in directories
            if not ignored_part(name)
            and not os.path.islink(os.path.join(current, name))
        )
        if depth >= MAX_DEPTH and directories:
            index.truncated = True
            directories[:] = []
        for name in sorted(names):
            if ignored_part(name):
                continue
            full = os.path.join(current, name)
            try:
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                stat = os.stat(full)
            except OSError:
                index.truncated = True
                continue
            if len(index.files) >= MAX_INDEXED_FILES:
                index.truncated = True
                return index
            relative = name if relative_dir == "." else f"{relative_dir}/{name}"
            index.files.append({
                "path": relative.replace(os.sep, "/"),
                "kind": file_kind(name),
                "size": int(stat.st_size),
                "mtime": float(stat.st_mtime),
            })
            index.total_bytes += int(stat.st_size)
    return index


def index_folder(root, *, fresh: bool = False) -> FolderIndex:
    root = Path(root).resolve(strict=True)
    key = str(root)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None and not fresh and now - cached.built_at < INDEX_TTL_S:
        return cached
    index = _walk(root)
    with _cache_lock:
        _cache[key] = index
    return index


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
