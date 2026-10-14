#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit PR #1485 replay: shortcut drafts, delivery identity and Cancel.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT in a fresh isolated
Dev app with outgoing networking blocked. Inspect the native footer capture.
"""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

SETUP = '''
from types import SimpleNamespace
import chat_send_probe as probe
from mixar.modules.space_mixie_chat.core import turn_transport, turn_events, chat_history
from mixar.modules.space_mixie_chat.ui.operators import quick_prompt_ops
probe.install()
turn_transport.create_turn_handler = probe.originals[(turn_transport, 'create_turn_handler')]
f = drv._review_send = SimpleNamespace(originals=[], commands=[], scene=drv.main_window().scene)
def replace(module, name, value):
    f.originals.append((module, name, getattr(module, name)))
    setattr(module, name, value)
def command(method, payload, callback, **kwargs):
    f.commands.append((method, payload, kwargs['command_id']))
replace(turn_transport, 'command', command)
replace(chat_history, 'archive_current', lambda *args: False)
replace(quick_prompt_ops, 'get_connection_manager', lambda: SimpleNamespace(is_connected=True))
f.scene.mixie_chat_messages.clear()
f.scene.mixie_chat_pending_attachments.clear()
f.scene.mixie_chat_mode = 'AGENT'
f.scene.mixie_chat_input = 'Keep my unfinished main draft: café.'
wm = bpy.context.window_manager
wm.mixie_chat_quick_prompt_mode = 'AGENT'
wm.mixie_chat_quick_prompt_input = 'Send only this shortcut.'
result = True
'''

QUICK = '''
from mixar.modules.space_mixie_chat.core import turn_events
from mixar.modules.space_mixie_chat.core.session import get_session_manager
import chat_send_probe as probe
f = drv._review_send
wm = bpy.context.window_manager
with bpy.context.temp_override(window=drv.main_window()):
    assert bpy.ops.mixie_chat.quick_prompt('EXEC_DEFAULT') == {'FINISHED'}
assert f.scene.mixie_chat_input == 'Keep my unfinished main draft: café.'
assert wm.mixie_chat_quick_prompt_input == ''
assert len(f.commands) == 1 and f.commands[0][1]['message'].endswith('Send only this shortcut.')
user = next(m for m in f.scene.mixie_chat_messages if m.sender == 'USER')
assert user.delivery_hint == '' and user.bubble_id == f.commands[0][2]
turn_events._consume('agent.command.result', {'command_id': user.bubble_id, 'ok': True})
get_session_manager().set_connected(f.scene)
probe.connected = False
wm.mixie_chat_quick_prompt_input = 'Keep this failed shortcut too.'
with bpy.context.temp_override(window=drv.main_window()):
    try:
        result = bpy.ops.mixie_chat.quick_prompt('EXEC_DEFAULT')
    except RuntimeError as exc:
        assert 'Not connected' in str(exc)
    else:
        assert result == {'CANCELLED'}
assert f.scene.mixie_chat_input == 'Keep my unfinished main draft: café.'
assert wm.mixie_chat_quick_prompt_input == 'Keep this failed shortcut too.'
assert len(f.commands) == 1
probe.connected = True
result = True
'''

DELIVERY = '''
from mixar.modules.space_mixie_chat.core import turn_transport, turn_events
from mixar.modules.space_mixie_chat.core.session import get_session_manager
f = drv._review_send
scene = f.scene
session = get_session_manager()
session.set_run(scene, 'qa-run', True)
from mixar.modules.space_mixie_chat.constants import SessionState
session.set_state(scene, SessionState.BUSY)
scene.mixie_chat_input = 'An interjection'
with bpy.context.temp_override(window=drv.main_window()):
    assert bpy.ops.mixie_chat.send_message() == {'FINISHED'}
last = [m for m in scene.mixie_chat_messages if m.sender == 'USER'][-1]
assert last.delivery_hint == 'queued'
identity = last.bubble_id
handler = turn_transport.create_turn_handler(scene.name)
assert handler.start_input_stream(scene.mixie_session_id, 'submit', answers=[{'answer': 'blue'}])
assert last.bubble_id == identity and last.delivery_hint == 'queued'
turn_events._consume('agent.command.result', {'command_id': f.commands[-1][2], 'ok': True})
assert last.bubble_id == identity and last.delivery_hint == 'queued'
turn_events._consume('agent.command.result', {'command_id': identity, 'ok': True})
assert last.delivery_hint == ''
session.set_connected(scene)
turn_events._turns['qa-completed'] = turn_events.Turn(scene.mixie_session_id, 'qa-completed', 'qa-run', complete=True)
before = len(scene.mixie_chat_messages)
turn_events._consume('agent.recovery.status', {'session_id': scene.mixie_session_id, 'info': {'status': 'unavailable'}})
assert scene.mixie_run_open and len(scene.mixie_chat_messages) == before
turn_events._consume('agent.turn.started', {'session_id': scene.mixie_session_id, 'turn_id': 'qa-wakeup', 'run_id': 'qa-run'})
assert scene.mixie_chat_state == 'BUSY'
turn_events._consume('agent.turn.event', {'session_id': scene.mixie_session_id, 'turn_id': 'qa-wakeup', 'seq': 0,
    'event': {'type': 'turn_end', 'status': 'completed'}})
assert scene.mixie_chat_state == 'IDLE' and not scene.mixie_run_open
result = True
'''




def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/agent-review'))
    out.mkdir(parents=True, exist_ok=True)
    qa.eval(f'import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); result=True')
    qa.step('install_transport_fixture', qa.eval, SETUP)
    try:
        qa.step('quick_prompt_preserves_both_drafts', qa.eval, QUICK)
        qa.step('delivery_and_expired_background_journal', qa.eval, DELIVERY)
        return {'drafts_preserved': True, 'delivery_identity': True,
                'background_run_preserved': True, 'backend_calls': 0}
    finally:
        qa.eval('''
import chat_send_probe as probe
from mixar.modules.space_mixie_chat.core import turn_transport
f = drv._review_send
f.scene.mixie_imagegen_is_generating = False
f.scene.mixie_chat_mode = 'AGENT'
if hasattr(f, 'area'):
    f.area.type = f.old_type
for module, name, original in reversed(f.originals):
    setattr(module, name, original)
turn_transport.cleanup_all_turn_handlers()
probe.uninstall()
result = True
''')


if __name__ == '__main__':
    run_scenario('agent_review_regressions_e2e', run)
