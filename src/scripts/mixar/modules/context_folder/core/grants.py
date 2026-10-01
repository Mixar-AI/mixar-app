# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which folders each chat session may read: the authority behind every RPC.

A folder id alone opens nothing. Send (main thread) grants a session exactly
the folders attached to its scene when the turn left; removing a folder
revokes it at once. RPC worker threads only ever READ this map — they must
not touch ``bpy`` — so the scene's attachment list is mirrored here.
"""

import threading

_lock = threading.Lock()
_grants: dict = {}  # session_id -> frozenset(folder_id)


def grant(session_id: str, folder_ids) -> None:
    if not session_id:
        return
    with _lock:
        _grants[str(session_id)] = frozenset(str(f) for f in folder_ids if f)


def revoke(session_id: str, folder_id: str) -> None:
    """Withdraw one folder from one session (another scene that attached the
    same folder keeps it)."""
    with _lock:
        folders = _grants.get(str(session_id or ""))
        if folders and folder_id in folders:
            _grants[str(session_id)] = folders - {str(folder_id)}


def is_granted(session_id: str, folder_id: str) -> bool:
    with _lock:
        return str(folder_id or "") in _grants.get(str(session_id or ""), frozenset())


def granted(session_id: str) -> frozenset:
    with _lock:
        return _grants.get(str(session_id or ""), frozenset())


def clear() -> None:
    with _lock:
        _grants.clear()
