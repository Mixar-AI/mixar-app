# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Backend-only MCP operation admission over the authenticated agent socket."""

from ..constants import BEGIN_OPERATION, END_OPERATION
from . import lease


def dispatch(method, params):
    if not isinstance(params, dict):
        return {"success": False, "error_type": "invalid_params", "error": "Expected an object"}
    if method == BEGIN_OPERATION:
        return lease.begin_operation(params)
    if method == END_OPERATION:
        return lease.end_operation(params)
    return {"success": False, "error_type": "unknown_method", "error": "Unknown MCP operation method"}


def handle_request(client, method, params, request_id, *, schedule=None):
    """No notification can acquire a lease; acknowledge after main-thread work."""
    if not request_id:
        return
    if schedule is None:
        from mixar.modules.space_mixie_chat.core.main_thread_executor import run_on_main_thread
        schedule = run_on_main_thread
    generation = lease.transport_generation()

    def run():
        if generation != lease.transport_generation() or not client.is_connected:
            return  # The old transport cannot authorize work after reconnect.
        try:
            result = dispatch(method, params)
        except Exception:
            result = {"success": False, "error_type": "handler_error",
                      "error": "MCP operation could not be admitted"}
        client.queue_response(request_id, result)

    schedule(run)
