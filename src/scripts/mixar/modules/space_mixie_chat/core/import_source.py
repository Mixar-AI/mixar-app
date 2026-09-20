# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Process-local import sources (#1251).

The twin of ``export_destination``: paths picked in Blender's native file
browser must never enter chat slots, HTTP payloads, checkpoints, logs, or
saved blend data. The import script pops the value so success and failure
have the same cleanup semantics.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_sources: dict[str, str] = {}


def set_source(session_id: str, filepath: str) -> None:
    if not session_id or not filepath:
        raise ValueError("session_id and filepath are required")
    with _lock:
        _sources[session_id] = filepath


def has_source(session_id: str) -> bool:
    with _lock:
        return bool(_sources.get(session_id))


def pop_source(session_id: str) -> str | None:
    with _lock:
        return _sources.pop(session_id, None)


def clear_source(session_id: str) -> None:
    with _lock:
        _sources.pop(session_id, None)


def clear_all_sources() -> None:
    with _lock:
        _sources.clear()
