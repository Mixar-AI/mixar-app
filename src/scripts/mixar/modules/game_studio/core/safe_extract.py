# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Extract a downloaded game build without trusting the archive.

Refused, with the whole extraction aborted: absolute paths, drive letters,
``..`` components (zip-slip), backslash tricks, symlinks and other special
entries, duplicate names, and archives whose declared size or entry count
is past the limits (zip bombs). Every file is written by this process —
on macOS no ``com.apple.quarantine`` xattr, on Windows no Mark-of-the-Web —
which is why only sha256-verified, moderator-approved builds get here.
Modes keep the owner's execute bit only (``0o755``/``0o644``; never setuid).
Worker threads only.
"""

from __future__ import annotations

import os
import shutil
import stat
import zipfile

MAX_TOTAL_BYTES = 8 * 1024 ** 3
MAX_ENTRIES = 50_000
_CHUNK = 1024 * 1024


class UnsafeArchive(Exception):
    pass


def _parts(name: str) -> list[str]:
    if "\x00" in name:
        raise UnsafeArchive(f"entry {name!r} contains a NUL byte")
    if "\\" in name:
        raise UnsafeArchive(f"entry {name!r} uses backslashes")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise UnsafeArchive(f"entry {name!r} is an absolute path")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise UnsafeArchive(f"entry {name!r} leaves the install folder")
    return parts


def _kind(info: zipfile.ZipInfo) -> str:
    mode = info.external_attr >> 16
    kind = stat.S_IFMT(mode)  # 0 when the archiver recorded permissions only
    if kind == stat.S_IFLNK:
        return "symlink"
    if info.is_dir() or kind == stat.S_IFDIR:
        return "dir"
    if kind not in (0, stat.S_IFREG):
        return "special"
    return "file"


def check(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Validate every entry before anything is written."""
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        raise UnsafeArchive(f"{len(infos)} entries is more than {MAX_ENTRIES}")
    total, seen = 0, set()
    for info in infos:
        parts = _parts(info.filename)
        kind = _kind(info)
        if kind in ("symlink", "special"):
            raise UnsafeArchive(f"entry {info.filename!r} is a {kind}")
        key = "/".join(parts).lower()  # case-insensitive volumes (macOS, Windows)
        if parts and key in seen and kind == "file":
            raise UnsafeArchive(f"entry {info.filename!r} appears twice")
        seen.add(key)
        total += max(0, info.file_size)
        if total > MAX_TOTAL_BYTES:
            raise UnsafeArchive("the archive unpacks to more than 8 GB")
    return infos


def extract(zip_path: str, dest: str, cancel=None) -> int:
    """Extract into the NEW folder ``dest`` (must not exist). Returns the
    file count. On any failure ``dest`` is removed."""
    if os.path.exists(dest):
        raise UnsafeArchive("the install folder already exists")
    root = os.path.realpath(dest)
    os.makedirs(root)
    count = 0
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for info in check(archive):
                if cancel is not None and cancel.is_set():
                    raise UnsafeArchive("cancelled")
                parts = _parts(info.filename)
                if not parts:
                    continue
                target = os.path.realpath(os.path.join(root, *parts))
                if os.path.commonpath([root, target]) != root:
                    raise UnsafeArchive(f"entry {info.filename!r} leaves the install folder")
                if _kind(info) == "dir":
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                written = 0
                with archive.open(info) as source, open(target, "xb") as sink:
                    while True:
                        chunk = source.read(_CHUNK)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > info.file_size:  # lying header
                            raise UnsafeArchive(f"entry {info.filename!r} is larger than declared")
                        sink.write(chunk)
                mode = info.external_attr >> 16
                os.chmod(target, 0o755 if mode & 0o111 else 0o644)
                count += 1
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return count


def make_executable(path: str) -> None:
    os.chmod(path, 0o755)


def inside(root: str, relative: str) -> str:
    """``root/relative`` resolved, refusing anything outside ``root``."""
    parts = _parts(str(relative or ""))
    if not parts:
        raise UnsafeArchive("empty entry point")
    root = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, *parts))
    if os.path.commonpath([root, target]) != root:
        raise UnsafeArchive(f"entry point {relative!r} leaves the install folder")
    return target
