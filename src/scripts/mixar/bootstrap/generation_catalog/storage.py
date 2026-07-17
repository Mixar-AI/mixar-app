# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Disk persistence for the stale-while-revalidate generation catalog."""

import json
import os
from typing import Any, Dict, Optional, Tuple

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_DISK_FILENAME = "generation_catalog.json"


def _data_dir() -> str:
    try:
        import bpy

        path = bpy.utils.user_resource("DATAFILES", path="mixar")
        if path:
            return path
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), ".mixar")


def _disk_path() -> str:
    return os.path.join(_data_dir(), _DISK_FILENAME)


def load() -> Optional[Tuple[Dict[str, Any], Optional[str]]]:
    """Return ``(data, etag)`` for a valid persisted payload, else None."""
    path = _disk_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            stored = json.load(file_handle)
        data = stored.get("data") if isinstance(stored, dict) else None
        if not isinstance(data, dict) or not data.get("capabilities"):
            return None
        return data, stored.get("etag") or None
    except Exception as exc:
        logger.warning("Generation catalog disk cache read failed: %s", exc)
        return None


def save(etag: Optional[str], data: Dict[str, Any]) -> None:
    """Persist the payload and ETag. Never raises."""
    path = _disk_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file_handle:
            json.dump({"etag": etag, "data": data}, file_handle)
    except Exception as exc:
        logger.warning("Generation catalog disk cache write failed: %s", exc)


def delete() -> None:
    """Remove persisted catalog data. Never raises."""
    try:
        path = _disk_path()
        if os.path.isfile(path):
            os.remove(path)
    except Exception as exc:
        logger.warning("Generation catalog disk cache delete failed: %s", exc)
