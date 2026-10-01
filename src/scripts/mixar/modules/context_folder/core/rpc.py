# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The ``context_folder.*`` JSON-RPC surface (backend → client).

Every request names a ``session_id`` and an opaque ``folder_id``; it is
served only when Send granted that session the folder (``grants.py``). The
work is file I/O, so it runs on a daemon thread and replies through the
socket's response queue — Blender's main thread is never blocked by a
search over a large folder.
"""

import threading

from ..constants import RPC_LIST, RPC_READ, RPC_SEARCH, RPC_VIEW_IMAGE
from . import grants, reader
from .errors import ContextFolderError, public_error
from .registry import get_registry


def _root_for(params: dict):
    session_id = str(params.get("session_id") or "")
    folder_id = str(params.get("folder_id") or "")
    if not grants.is_granted(session_id, folder_id):
        raise ContextFolderError(
            "folder_not_attached",
            "That folder is not attached to this chat; ask the user to attach it and send again",
        )
    return get_registry().resolve(folder_id)


def dispatch(method: str, params: dict) -> dict:
    """Serve one request synchronously. Never raises; errors are path-free."""
    params = params if isinstance(params, dict) else {}
    try:
        if method == RPC_LIST:
            return reader.list_files(_root_for(params), params.get("subfolder") or "",
                                     params.get("kind") or None, params.get("offset") or 0,
                                     params.get("limit") or 200)
        if method == RPC_READ:
            return reader.read_text(_root_for(params), params.get("path"),
                                    params.get("start_line"), params.get("end_line"))
        if method == RPC_SEARCH:
            return reader.search(_root_for(params), params.get("query"),
                                 params.get("max_results") or 60)
        if method == RPC_VIEW_IMAGE:
            return reader.preview_image(_root_for(params), params.get("path"),
                                        params.get("max_dim") or 1024)
        raise ContextFolderError("unknown_method", "This Mixar build does not support that folder operation")
    except Exception as exc:  # noqa: BLE001 — every failure becomes a path-free reply
        return public_error(exc)


def handle_request(method: str, params: dict, respond) -> None:
    """Answer on a worker thread; ``respond(result)`` queues the reply."""

    def _worker():
        respond(dispatch(method, params))

    threading.Thread(target=_worker, daemon=True, name="MixarContextFolderRPC").start()
