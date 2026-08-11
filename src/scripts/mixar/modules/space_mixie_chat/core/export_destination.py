# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Process-local export destinations.

Paths selected in Blender's native file browser must never enter chat slots,
HTTP payloads, checkpoints, logs, or saved blend data.  The export script pops
the value so success and failure have the same cleanup semantics.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_destinations: dict[str, str] = {}


def set_destination(session_id: str, filepath: str) -> None:
    if not session_id or not filepath:
        raise ValueError("session_id and filepath are required")
    with _lock:
        _destinations[session_id] = filepath


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
    try:
        from .export_preflight import clear_repair_cache
        clear_repair_cache()
    except ImportError:
        pass
