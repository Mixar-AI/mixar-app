# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Process-local export destinations.

Paths selected in Blender's native file browser must never enter chat slots,
HTTP payloads, checkpoints, logs, or saved blend data.  The export script pops
the value so success and failure have the same cleanup semantics.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_destinations: dict[str, str] = {}
# session_id -> (request_id, folder, monotonic time): the folder of the last
# picked destination, so a retry of the same agent request (a failed first
# attempt, a resumed tool call) never opens a second picker in one turn.
_folders: dict[str, tuple[str, str, float]] = {}
FOLDER_MEMORY_SECONDS = 15 * 60


def set_destination(session_id: str, filepath: str) -> None:
    if not session_id or not filepath:
        raise ValueError("session_id and filepath are required")
    with _lock:
        _destinations[session_id] = filepath


def remember_export_folder(session_id: str, request_id: str, folder: str) -> None:
    """Remember ``folder`` for ``request_id`` (the file_save question's bubble
    id, which the backend issued); the next pick overwrites it."""
    if not session_id or not folder:
        raise ValueError("session_id and folder are required")
    with _lock:
        _folders[session_id] = (str(request_id or ""), folder, time.monotonic())


def remembered_export_folder(session_id: str, request_id: str) -> str | None:
    """The folder picked for ``request_id``, or None when nothing was
    remembered, the request id differs, or the memory is older than
    ``FOLDER_MEMORY_SECONDS``. The path stays on this machine."""
    with _lock:
        entry = _folders.get(session_id)
        if entry is None:
            return None
        stored_id, folder, stamp = entry
        if time.monotonic() - stamp > FOLDER_MEMORY_SECONDS:
            _folders.pop(session_id, None)
            return None
    if stored_id != str(request_id or ""):
        return None
    return folder


def has_destination(session_id: str) -> bool:
    with _lock:
        return bool(_destinations.get(session_id))


def pop_destination(session_id: str) -> str | None:
    with _lock:
        return _destinations.pop(session_id, None)


def clear_destination(session_id: str) -> None:
    with _lock:
        _destinations.pop(session_id, None)
    try:
        from .export_preflight import clear_repair_cache
        clear_repair_cache(session_id)
    except ImportError:
        pass


def clear_all_destinations() -> None:
    with _lock:
        _destinations.clear()
        _folders.clear()
    try:
        from .export_preflight import clear_repair_cache
        clear_repair_cache()
    except ImportError:
        pass
