# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""A JSON-RPC error response reaches the request's callback as the error.

The server serialises every response field, so an error response also
carries ``"result": null``. Picking the result whenever the key was present
handed the callback ``None`` for every request-level refusal — a turn command
refused at the guest door (rate limit, kill switch) was never settled and the
chat sat BUSY until a relaunch.
"""
from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.space_mixie_chat.core.jsonrpc_client import JSONRPCWebSocketClient  # noqa: E402

ERROR = {"code": -32021, "message": "Guest limit reached for this hour.",
         "data": {"status_code": 429, "data": {"code": "guest_rate_limited"}}}


def _socket():
    socket = JSONRPCWebSocketClient("http://unused", "test")
    socket._connected = socket._handshake_complete = True
    return socket


def _answer(socket, msg):
    seen = []
    socket._pending_callbacks[msg["id"]] = seen.append
    socket._handle_message(msg)
    return seen


def test_an_error_response_with_a_null_result_delivers_the_error():
    seen = _answer(_socket(), {"jsonrpc": "2.0", "id": "req_1", "result": None, "error": ERROR})
    assert seen == [ERROR]


def test_a_result_response_still_delivers_the_result():
    seen = _answer(_socket(), {"jsonrpc": "2.0", "id": "req_2", "result": {"state": "accepted"}, "error": None})
    assert seen == [{"state": "accepted"}]


def test_a_null_result_without_an_error_is_delivered_as_is():
    seen = _answer(_socket(), {"jsonrpc": "2.0", "id": "req_3", "result": None})
    assert seen == [None]
