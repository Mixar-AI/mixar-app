# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Disk-only asset cache shared by enqueue downloads and sandbox consumers.

No bpy access. Callers enforce the asset-host allowlist before BOTH reads and
downloads. Only background preparation may call download(); cached_path() never
waits for a transfer. Atomic publication keeps partial files out of the GUI.
"""

import hashlib
import os
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .asset_cache_directory import CacheDirectory

_LOCK = threading.Lock()
_DIRECTORY_LOCK = threading.Lock()
_IN_FLIGHT = {}
_DIRECTORY = None


def _name(url):
    parts = urlsplit(str(url))
    # Presigned credentials rotate without changing the asset. Retain content
    # selectors such as versionId, and the full host/path (including bucket).
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("x-amz-")
             and k.lower() not in {"awsaccesskeyid", "signature", "expires"}]
    key = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    digest = hashlib.sha256(key.encode()).hexdigest()
    suffix = ".blend" if parts.path.lower().endswith(".blend") else ".bin"
    return digest + suffix


def _directory():
    """Worker-only lazy creation; readers never acquire this lock."""
    global _DIRECTORY
    with _DIRECTORY_LOCK:
        directory = _DIRECTORY
        if directory is not None:
            try:
                directory.path.lstat()
            except FileNotFoundError:
                # A temporary-file cleaner may remove an idle cache. Allocate
                # a fresh private root; never recreate or adopt the old name.
                directory = None
        if directory is None:
            _DIRECTORY = CacheDirectory()
        return _DIRECTORY


def cached_path(url):
    """Return a completed local file, or None immediately; never download."""
    directory = _DIRECTORY
    if directory is None:
        return None
    try:
        with directory.open() as access:
            return access.hit(_name(url))
    except OSError:
        return None


def download(url, *, opener, timeout=30):
    """Stream one asset on a background thread, coalescing duplicate transfers."""
    name = _name(url)
    hit = cached_path(url)
    if hit:
        return hit
    with _LOCK:
        pending = _IN_FLIGHT.get(name)
        owner = pending is None
        if owner:
            pending = threading.Event()
            _IN_FLIGHT[name] = pending
    if not owner:
        if not pending.wait(timeout):
            raise TimeoutError("Asset download is still pending")
        hit = cached_path(url)
        if hit:
            return hit
        raise OSError("Asset download failed")
    response = None
    deadline = time.monotonic() + timeout
    try:
        # Recheck after acquiring ownership: another transfer may have just
        # published and removed its event between our first check and the lock.
        hit = cached_path(url)
        if hit:
            return hit
        with _directory().open() as access:
            partial = None
            try:
                response = opener(str(url), timeout=timeout)
                partial, fd = access.partial()
                with os.fdopen(fd, "wb") as out:
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        if time.monotonic() > deadline:
                            raise TimeoutError("Asset download exceeded its preparation budget")
                        out.write(chunk)
                        size += len(chunk)
                length = getattr(response, "headers", {}).get("Content-Length")
                if not size or (length is not None and size != int(length)):
                    raise OSError("Asset download was empty or incomplete")
                access.publish(partial, name)
                partial = None
                hit = access.hit(name)
                if hit is None:
                    raise OSError("Published asset cache entry is unsafe")
                return hit
            finally:
                if partial is not None:
                    access.discard(partial)
    finally:
        try:
            if response is not None:
                response.close()
        finally:
            with _LOCK:
                _IN_FLIGHT.pop(name, None)
                pending.set()
