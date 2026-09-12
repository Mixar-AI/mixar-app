# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local transport boundary for the composer scenario; real send operator/UI.

Loaded in the isolated QA app. No registered operators or input properties
are replaced. The production send path builds its payload and optimistic
transcript; only connection/auth checks and the outgoing SSE transport are
replaced. Restore in finally. Run the app with external networking blocked.
"""

from types import SimpleNamespace

import bpy
from mixar.modules.space_mixie_chat.ui.operators import chat_ops

calls = []
originals = {}
connected = True


def install():
    global connected
    assert not originals, 'send probe already installed'
    assert not bpy.context.scene.mixie_chat_is_busy, 'QA scene must be idle'
    for name in ('get_connection_manager', 'get_jsonrpc_client',
                 'create_sse_handler', 'get_auth_token'):
        originals[name] = getattr(chat_ops, name)
    connected = True
    chat_ops.get_connection_manager = lambda: SimpleNamespace(is_connected=connected)
    chat_ops.get_jsonrpc_client = lambda: SimpleNamespace(connection_id='qa-local')
    chat_ops.get_auth_token = lambda: 'qa-local-placeholder'
    chat_ops.create_sse_handler = lambda **kwargs: SimpleNamespace(start_stream=record)
    calls.clear()
    chat_ops.get_session_manager().set_connected(bpy.context.scene)
    bpy.context.window_manager.mixie_chat_is_logged_in = True


def record(**payload):
    calls.append(payload)
    return True


def settle(scene):
    """A local reply ends the fixture turn; never claims a backend response."""
    for i in reversed(range(len(scene.mixie_chat_messages))):
        if scene.mixie_chat_messages[i].bubble_id.startswith(chat_ops.TEMP_PLACEHOLDER_PREFIX):
            scene.mixie_chat_messages.remove(i)
    for message in scene.mixie_chat_messages:
        message.loader_visible = False
    chat_ops.get_session_manager().set_connected(scene)


def uninstall():
    for name, value in originals.items():
        setattr(chat_ops, name, value)
    originals.clear()
    settle(bpy.context.scene)
