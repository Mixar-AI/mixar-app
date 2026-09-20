# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Disk persistence for the stale-while-revalidate agent models catalog.

Mirrors `bootstrap/generation_catalog/storage.py`. The payload carries no
credential material — it is the provider/model list the BYOK dropdowns render —
but it IS account-shaped: `eligible` is derived from the caller's subscription
tier, so it is deleted on logout rather than left for the next account.
"""

import json
import os
import tempfile
from typing import Any, Dict, Optional, Tuple

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_DISK_FILENAME = "agent_models.json"
_resolved_disk_path: Optional[str] = None


def _data_dir() -> str:
    try:
        import bpy

        path = bpy.utils.user_resource("DATAFILES", path="mixar")
        # Under the pytest bpy mock `user_resource` returns a truthy MagicMock,
        # and real Blender prints-and-swallows a creation failure, returning "".
        if isinstance(path, str) and path:
            return path
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), ".mixar")


def _disk_path() -> str:
    """Return the cache path resolved on the caller's first access.

    ``initialize_disk_path()`` is called on Blender's main thread before any
    fetch worker can persist a response, so a worker never reaches into
    ``bpy.utils`` — background threads must not touch bpy.
    """
    global _resolved_disk_path
    if _resolved_disk_path is None:
        _resolved_disk_path = os.path.join(_data_dir(), _DISK_FILENAME)
    return _resolved_disk_path


def initialize_disk_path() -> str:
    """Resolve and cache the persistence path on Blender's main thread."""
    return _disk_path()


def set_path_for_tests(path: Optional[str]) -> None:
    """Point the cache at ``path`` (or reset resolution when None)."""
    global _resolved_disk_path
    _resolved_disk_path = path


def load() -> Optional[Tuple[Dict[str, Any], Optional[str]]]:
    """Return ``(data, etag)`` for a valid persisted payload, else None."""
    path = _disk_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            stored = json.load(file_handle)
        data = stored.get("data") if isinstance(stored, dict) else None
        # An authoritative empty catalog (`providers: []`) is valid and must
        # survive a reload — only a missing/!list `providers` is malformed.
        if not isinstance(data, dict) or not isinstance(data.get("providers"), list):
            return None
        return data, stored.get("etag") or None
    except Exception as exc:
        logger.warning("Agent models disk cache read failed: %s", exc)
        return None


def save(etag: Optional[str], data: Dict[str, Any]) -> None:
    """Persist the payload and ETag. Never raises."""
    path = _disk_path()
    temp_path = None
    try:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{_DISK_FILENAME}.", suffix=".tmp", dir=directory
        )
        with os.fdopen(fd, "w", encoding="utf-8") as file_handle:
            json.dump({"etag": etag, "data": data}, file_handle)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    except Exception as exc:
        logger.warning("Agent models disk cache write failed: %s", exc)
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def delete() -> None:
    """Remove persisted catalog data. Never raises."""
    try:
        path = _disk_path()
        if os.path.isfile(path):
            os.remove(path)
    except Exception as exc:
        logger.warning("Agent models disk cache delete failed: %s", exc)
