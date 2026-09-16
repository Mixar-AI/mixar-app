# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A live agent socket follows consent changes without waiting for reconnect."""
from unittest.mock import MagicMock
from mixar.modules.common.analytics import preferences
from mixar.modules.space_mixie_chat.core import jsonrpc_client


def test_consent_change_sends_new_value_and_retains_persistence_result(monkeypatch):
    client = MagicMock(is_connected=True)
    monkeypatch.setattr(preferences, 'add_config', lambda key, value: False)
    monkeypatch.setattr(jsonrpc_client, 'get_jsonrpc_client', lambda: client)
    assert preferences.set_enabled(False) is False
    args, kwargs = client.send_request.call_args
    assert args == ('system.set_context', {'telemetry_consent': False})
    kwargs['on_result']({'updated': True})
    client._ws.close.assert_not_called()
    kwargs['on_result']({'code': -32020, 'message': 'timeout'})
    client._ws.close.assert_called_once()


def test_offline_consent_only_persists_for_next_handshake(monkeypatch):
    client = MagicMock(is_connected=False)
    monkeypatch.setattr(preferences, 'add_config', lambda key, value: True)
    monkeypatch.setattr(jsonrpc_client, 'get_jsonrpc_client', lambda: client)
    assert preferences.set_enabled(True) is True
    client.send_request.assert_not_called()
