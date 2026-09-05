# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Safe extraction of llama.cpp release archives.

Handles the two layouts the b-series releases actually ship:

- macOS/Linux ``.tar.gz``: everything under one top-level
  ``llama-<tag>/`` directory (including relative dylib symlink chains);
- Windows ``.zip``: FLAT — no top-level directory at all.

``safe_extract`` normalizes both so *dest_dir* directly contains
``llama-server``/``llama-server.exe`` plus its libraries.

Safety: every member path is validated (no absolute paths, no drive
letters, no ``..`` components) and link members must resolve inside the
destination, so a malicious archive cannot write outside *dest_dir*.

No bpy imports — safe on any background thread.
"""

import os
import posixpath
import subprocess
import sys
import tarfile
import zipfile

from mixar.config.logging_config import get_logger

from ..constants import LOG_PREFIX

logger = get_logger(__name__)


class ArchiveError(Exception):
    """Extraction failed or the archive is unsafe/malformed."""


def _split_clean(name):
    """Member path -> list of components; raises on traversal attempts."""
    raw = name.replace("\\", "/")
    if raw.startswith("/") or raw.startswith("//"):
        raise ArchiveError(f"Absolute member path rejected: {name!r}")
    if len(raw) >= 2 and raw[1] == ":":
        raise ArchiveError(f"Drive-letter member path rejected: {name!r}")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ArchiveError(f"Path-traversal member rejected: {name!r}")
    return parts


def _strip_prefix(all_parts):
    """Number of leading components to strip (1 for a sole top-level dir).

    A single shared top-level component means the tarball nests everything
    under ``llama-<tag>/`` — strip it. Flat zips (and anything with more
    than one top-level entry) keep 0.
    """
    tops = {parts[0] for parts in all_parts if parts}
    if len(tops) == 1 and any(len(parts) > 1 for parts in all_parts):
        return 1
    return 0


def _validate_link(parts, linkname, dest_dir):
    """A tar link target must land inside dest_dir (relative, contained)."""
    raw = (linkname or "").replace("\\", "/")
    if raw.startswith("/"):
        raise ArchiveError(f"Absolute link target rejected: {linkname!r}")
    member_dir = posixpath.dirname("/".join(parts))
    resolved = posixpath.normpath(posixpath.join(member_dir, raw))
    if resolved.startswith(".."):
        raise ArchiveError(f"Link escaping the archive rejected: {linkname!r}")
    target = os.path.normpath(os.path.join(dest_dir, *resolved.split("/")))
    base = os.path.normpath(dest_dir)
    if not (target == base or target.startswith(base + os.sep)):
        raise ArchiveError(f"Link escaping dest_dir rejected: {linkname!r}")


def _extract_tar(archive_path, dest_dir):
    with tarfile.open(archive_path, "r:gz") as tar:
        members = tar.getmembers()
        parts_by_member = [(m, _split_clean(m.name)) for m in members]
        strip = _strip_prefix([p for _, p in parts_by_member])
        for member, parts in parts_by_member:
            out_parts = parts[strip:]
            if not out_parts:
                continue  # the stripped top-level dir entry itself
            if not (member.isfile() or member.isdir() or member.issym()
                    or member.islnk()):
                # Devices/FIFOs have no business in a release archive.
                raise ArchiveError(f"Special member rejected: {member.name!r}")
            if member.issym() or member.islnk():
                _validate_link(out_parts, member.linkname, dest_dir)
            member.name = "/".join(out_parts)
            try:
                # We validated every member ourselves; 'tar' keeps the
                # (already-checked) symlinks working on Python >= 3.12,
                # where the default extraction filter would tighten.
                tar.extract(member, dest_dir, set_attrs=True, filter="tar")
            except TypeError:
                tar.extract(member, dest_dir, set_attrs=True)
            if member.isfile() and os.name == "posix" and (member.mode & 0o111):
                _chmod_exec(os.path.join(dest_dir, *out_parts))


def _extract_zip(archive_path, dest_dir):
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        parts_by_info = [(i, _split_clean(i.filename)) for i in infos]
        strip = _strip_prefix([p for _, p in parts_by_info])
        for info, parts in parts_by_info:
            out_parts = parts[strip:]
            if not out_parts:
                continue
            target = os.path.join(dest_dir, *out_parts)
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)


def _chmod_exec(path):
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass


def _ensure_executables(dest_dir):
    """Belt-and-braces 0o755 on the server binaries (POSIX only)."""
    if os.name != "posix":
        return
    for root, _dirs, files in os.walk(dest_dir):
        for name in files:
            if name.startswith("llama-"):
                _chmod_exec(os.path.join(root, name))


def _strip_quarantine(dest_dir):
    """macOS: drop com.apple.quarantine so Gatekeeper never blocks the
    downloaded binaries. Failure is ignored — our own download path does
    not stamp the xattr; this is defensive."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["xattr", "-dr", "com.apple.quarantine", dest_dir],
            capture_output=True, timeout=30, check=False,
        )
    except Exception as exc:
        logger.debug("%s quarantine strip skipped: %s", LOG_PREFIX, exc)


def safe_extract(archive_path, dest_dir):
    """Extract *archive_path* (tar.gz or zip) into *dest_dir*, normalized.

    After a successful return, *dest_dir* directly contains
    ``llama-server`` (POSIX, mode 0o755) or ``llama-server.exe`` and every
    library next to it, regardless of which archive layout was shipped.

    Raises:
        ArchiveError: unsafe member, unsupported format, or corrupt data.
    """
    os.makedirs(dest_dir, exist_ok=True)
    try:
        if archive_path.endswith(".zip"):
            _extract_zip(archive_path, dest_dir)
        elif archive_path.endswith((".tar.gz", ".tgz")):
            _extract_tar(archive_path, dest_dir)
        else:
            raise ArchiveError(f"Unsupported archive type: {archive_path!r}")
    except ArchiveError:
        raise
    except (tarfile.TarError, zipfile.BadZipFile, OSError, EOFError) as exc:
        raise ArchiveError(f"Extraction failed: {exc}") from exc
    _ensure_executables(dest_dir)
    _strip_quarantine(dest_dir)
