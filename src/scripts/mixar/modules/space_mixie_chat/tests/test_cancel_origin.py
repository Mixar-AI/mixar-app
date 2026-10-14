# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every cancel says what triggered it.

Prod: 330 cancels a week were logged ``user_abort`` — but New Chat, a history
switch, closing a tab, an undo that removes a scene and loading a file all
cancel the live run too. The origin rides on the cancel so the backend (logs,
Langfuse) can tell the user's Stop from the app's side effects.
"""
from unittest.mock import MagicMock


def test_the_origin_rides_on_the_cancel_and_is_omitted_when_unknown(monkeypatch):
    from mixar.modules.common.agent_rpc import client
    from mixar.modules.space_mixie_chat.ui.operators import session_ops

    sent = MagicMock()
    monkeypatch.setattr(client, 'request', sent)
    session_ops._send_cancel_request('sess-1', 'new_chat')
    session_ops._send_cancel_request('sess-2')
    assert sent.call_args_list[0].args == ('cancel', {'session_id': 'sess-1', 'origin': 'new_chat'})
    assert sent.call_args_list[1].args == ('cancel', {'session_id': 'sess-2'})


def test_a_file_load_labels_its_cancel(monkeypatch):
    from mixar.modules.common.agent_rpc import client
    from mixar.modules.space_mixie_chat.core import file_handlers

    sent = MagicMock()
    monkeypatch.setattr(client, 'request', sent)
    file_handlers._send_abort_request('sess-3')
    assert sent.call_args.args == ('cancel', {'session_id': 'sess-3', 'origin': 'file_load'})
