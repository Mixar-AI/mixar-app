# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The agent WebSocket handshake reports the RUNNING build's version.

The backend turns the handshake's ``addon_version`` into the
``X-Client-Version`` header its force-update gate judges every agent command
by. Until 4.0.1 no caller filled the field, so every build sent the
constructor default ``"1.0.0"`` and the newest release was refused as
outdated the moment the backend moved agent commands onto the WebSocket
(prod, 2026-09-24). ``create_jsonrpc_client`` now resolves it from the same
source as ``PUT /me/client-version`` and an unknown version is OMITTED, never
replaced by a placeholder.
"""

from unittest.mock import patch

from mixar.modules.space_mixie_chat.core import jsonrpc_client as jc
from mixar.modules.common.updates.core import update_checker

RUNTIME = "mixar.modules.common.updates.core.update_checker.get_runtime_version"


def test_create_client_reports_runtime_version():
    with patch(RUNTIME, return_value="4.0.0"):
        client = jc.create_jsonrpc_client("http://localhost:8000", "conn")
    try:
        assert client._addon_version == "4.0.0"
    finally:
        jc.cleanup_jsonrpc_client()


def test_no_caller_default_is_a_placeholder():
    client = jc.JSONRPCWebSocketClient("http://localhost:8000", "conn")
    assert client._addon_version is None
    assert client._blender_version is None


def test_explicit_version_wins():
    with patch(RUNTIME, return_value="4.0.0"):
        client = jc.create_jsonrpc_client(
            "http://localhost:8000", "conn", addon_version="9.9.9"
        )
    try:
        assert client._addon_version == "9.9.9"
    finally:
        jc.cleanup_jsonrpc_client()


def test_unknown_version_is_omitted_from_handshake():
    with patch(RUNTIME, return_value=None):
        client = jc.create_jsonrpc_client("http://localhost:8000", "conn")
    try:
        assert client._addon_version is None
    finally:
        jc.cleanup_jsonrpc_client()
