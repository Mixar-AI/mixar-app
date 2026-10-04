# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Disk-only asset cache shared by enqueue downloads and sandbox consumers.

No bpy access. Callers enforce the asset-host allowlist before BOTH reads and
downloads. Only background preparation may call download(); cached_path() never
waits for a transfer. Atomic publication keeps partial files out of the GUI.
"""

import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_LOCK = threading.Lock()
_IN_FLIGHT = {}


def _path(url):
    parts = urlsplit(str(url))
    # Presigned credentials rotate without changing the asset. Retain content
    # selectors such as versionId, and the full host/path (including bucket).
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("x-amz-")
             and k.lower() not in {"awsaccesskeyid", "signature", "expires"}]
    key = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    digest = hashlib.sha256(key.encode()).hexdigest()
    suffix = ".blend" if parts.path.lower().endswith(".blend") else ".bin"
    return Path(tempfile.gettempdir()) / "mixar_agent_assets" / (digest + suffix)


def cached_path(url):
    """Return a completed local file, or None immediately; never download."""
    path = _path(url)
    try:
        return str(path) if path.is_file() and path.stat().st_size > 0 else None
    except OSError:
        return None


def download(url, *, opener, timeout=30):
    """Stream one asset on a background thread, coalescing duplicate transfers."""
    path = _path(url)
    hit = cached_path(url)
    if hit:
        return hit
    with _LOCK:
        pending = _IN_FLIGHT.get(path)
        owner = pending is None
        if owner:
            pending = threading.Event()
            _IN_FLIGHT[path] = pending
    if not owner:
        if not pending.wait(timeout):
            raise TimeoutError("Asset download is still pending")
        hit = cached_path(url)
        if hit:
            return hit
        raise OSError("Asset download failed")
    partial = None
    response = None
    deadline = time.monotonic() + timeout
    try:
        # Recheck after acquiring ownership: another transfer may have just
        # published and removed its event between our first check and the lock.
        hit = cached_path(url)
        if hit:
            return hit
        path.parent.mkdir(parents=True, exist_ok=True)
        response = opener(str(url), timeout=timeout)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as out:
            partial = out.name
            size = 0
            while chunk := response.read(1024 * 1024):
                if time.monotonic() > deadline:
                    raise TimeoutError("Asset download exceeded its preparation budget")
                out.write(chunk)
                size += len(chunk)
        length = getattr(response, "headers", {}).get("Content-Length")
        if not size or (length is not None and size != int(length)):
            raise OSError("Asset download was empty or incomplete")
        os.replace(partial, path)
        partial = None
        return str(path)
    finally:
        try:
            if response is not None:
                response.close()
        finally:
            try:
                if partial is not None:
                    Path(partial).unlink(missing_ok=True)
            finally:
                with _LOCK:
                    _IN_FLIGHT.pop(path, None)
                    pending.set()
