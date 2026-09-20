# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared agent RPC facade. All commands use the authenticated agent socket."""

import threading
import uuid


class AgentRPCError(RuntimeError):
    def __init__(self, message, status_code=503, data=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.data = data or {}


def get_client():
    from mixar.modules.space_mixie_chat.core.jsonrpc_client import get_jsonrpc_client
    client = get_jsonrpc_client()
    if client is None or not client.is_connected:
        raise AgentRPCError('Agent is reconnecting. Please try again when connected.')
    if not getattr(client, 'agent_ws_supported', False):
        raise AgentRPCError('This server needs the WebSocket agent update.', 426)
    return client


def call(method, params, callback):
    """Nonblocking RPC. Callback executes off the main thread exactly once."""
    client = get_client()
    try:
        return client.send_request(method, params, on_result=callback)
    except ValueError as exc:
        raise AgentRPCError(str(exc), 413) from exc
    except Exception as exc:
        raise AgentRPCError('Agent connection is busy. Please try again.', 503) from exc


def command(method, payload, callback, command_id=None):
    command_id = command_id or str(uuid.uuid4())
    call('agent.' + method, {'command_id': command_id, 'payload': payload}, callback)
    return command_id


def request(method, payload=None, *, mutation=False, timeout=35):
    """Blocking convenience for existing settings worker threads; never UI callbacks."""
    if threading.current_thread() is threading.main_thread():
        raise RuntimeError('Blocking agent RPC must run on a worker thread')
    done = threading.Event()
    result = []
    def received(value):
        result.append(value)
        done.set()
    if mutation:
        command(method, payload or {}, received)
    else:
        call('agent.' + method, {'payload': payload or {}}, received)
    if not done.wait(timeout):
        raise AgentRPCError('Delivery is uncertain. Reconnect to check the command outcome.', 504)
    value = result[0]
    if isinstance(value, dict) and isinstance(value.get('code'), int) and value['code'] < 0:
        data = value.get('data') or {}
        raise AgentRPCError(value.get('message', 'Agent request failed'), data.get('status_code', 503), data)
    if isinstance(value, dict) and value.get('state') == 'pending':
        raise AgentRPCError('The command is still pending. Its outcome is not confirmed.', 504)
    if isinstance(value, dict) and value.get('state') == 'complete':
        value = value.get('result') or {}
        if not value.get('ok'):
            raise AgentRPCError(value.get('message', 'Agent request failed'), value.get('status_code', 503))
        value = value.get('data', value)
    return value
