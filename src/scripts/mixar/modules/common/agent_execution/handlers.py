# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""``agent.execution.*`` JSON-RPC handlers (parent / foreground side).

Requests arrive on the WebSocket thread. Every handler's bpy work is
scheduled onto the main thread and the reply goes back through
``queue_response`` on the SAME request id — the WS thread never blocks and
never touches bpy.
"""

from __future__ import annotations

from typing import Callable, Optional

from mixar.config.logging_config import get_logger

from . import bindings
from .commit import append_collection
from .journal import get_journal

logger = get_logger(__name__)

EXECUTION_PREFIX = "agent.execution."
METHODS = ("activate", "bind_task", "status", "commit", "revoke")


def dispatch(method: str, params: dict) -> dict:
    """Pure dispatch (main thread): method → result dict. Never raises."""
    name = method[len(EXECUTION_PREFIX):] if method.startswith(EXECUTION_PREFIX) else method
    params = params if isinstance(params, dict) else {}
    try:
        if name == "activate":
            return bindings.activate(params)
        if name == "bind_task":
            return bindings.bind_task(params)
        if name == "status":
            ids = params.get("operation_ids") or []
            return {"success": True, "operations": get_journal().ops_status(ids)}
        if name == "commit":
            return append_collection(params)
        if name == "revoke":
            return bindings.revoke(params)
        return {"success": False, "error": f"unknown execution method {method}",
                "error_type": "unknown_method"}
    except Exception as exc:  # noqa: BLE001 — a handler crash must still reply
        logger.error("execution handler %s failed: %s", method, exc, exc_info=True)
        return {"success": False, "error": f"{type(exc).__name__}: {exc}",
                "error_type": "handler_error"}


def _default_schedule(fn: Callable[[], None]) -> None:
    from mixar.modules.space_mixie_chat.core.main_thread_executor import run_on_main_thread

    run_on_main_thread(fn)


def _default_respond(request_id: str, result: dict) -> None:
    from mixar.modules.space_mixie_chat.core.jsonrpc_client import get_jsonrpc_client

    client = get_jsonrpc_client()
    if client is not None:
        client.queue_response(request_id, result)


def handle_execution_request(
    method: str,
    params: dict,
    request_id: Optional[str],
    *,
    schedule: Callable[[Callable[[], None]], None] = _default_schedule,
    respond: Callable[[str, dict], None] = _default_respond,
) -> None:
    """WS-thread entry: defer to the main thread, reply later. Returns None."""

    def _run():
        result = dispatch(method, params)
        if request_id:
            respond(request_id, result)

    schedule(_run)
    return None
