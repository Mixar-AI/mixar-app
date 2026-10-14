# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A published set of single files that the agent sees as ONE folder.

Files attached one by one (a video, a PDF, a text note) have no common root,
so the registry publishes them as a ``FileSet`` under a synthetic folder id.
Everything downstream — the indexer, the path resolver, the reader, the
manifest — accepts a ``FileSet`` wherever it accepts a directory root: a
member's folder-relative path is exactly its unique display name, and nothing
outside the member paths is ever touched.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileSet:
    set_id: str
    # ((name, absolute path), ...) as published; resolved strictly on access.
    members: tuple = ()

    @property
    def files(self) -> dict:
        """``name -> Path`` for every member that still exists as a regular
        file; a vanished member is simply omitted and the set stays usable."""
        files = {}
        for name, root in self.members:
            try:
                path = Path(root).resolve(strict=True)
            except OSError:
                continue
            if path.is_file():
                files[name] = path
        return files

    def member(self, name: str):
        """The resolved path of one member, or ``None``."""
        return self.files.get(name)


def is_file_set(root) -> bool:
    return isinstance(root, FileSet)


def local_roots(root) -> list:
    """Absolute local prefixes that must never reach the wire: the directory
    root itself, or every member's parent directory for a file set."""
    if is_file_set(root):
        return sorted({str(path.parent) for path in root.files.values()}, key=len, reverse=True)
    return [str(root)]
