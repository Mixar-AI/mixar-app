#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit History recovery and timer teardown in an isolated Dev app.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Run with external
connections blocked. History files are redirected into a temporary directory;
only status/replay transport boundaries are replaced. Inspect the PNGs.
"""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


SETUP = '''
import tempfile
from types import SimpleNamespace
from mixar.modules.space_mixie_chat.core import (
    chat_history, jsonrpc_client, turn_events, turn_transport)
from mixar.modules.space_mixie_chat.ui.operators import history_ops
from mixar.modules.space_mixie_chat.core.session import get_session_manager
assert not turn_transport._handlers, 'Use a fresh isolated app'
f = drv._turn_lifecycle = SimpleNamespace(
    scratch=tempfile.TemporaryDirectory(prefix='mixar-turn-qa-'),
    originals=[], calls=[], scene=drv.main_window().scene)
def replace(module, name, value):
    f.originals.append((module, name, getattr(module, name)))
    setattr(module, name, value)
replace(chat_history, '_mixar_home', lambda: f.scratch.name)
replace(chat_history, 'DEV_MODE', False)
replace(history_ops, 'send_cancel_request_async', lambda sid: f.calls.append(('cancel', sid)))
info = {'turn_id': 'qa-old-turn', 'run_id': 'qa-run',
        'status': 'abandoned', 'replay_available': True}
def rpc(method, params, on_result=None):
    f.calls.append((method, params))
    if method == 'agent.status':
        result = {'turns': {'qa-history': info}} if 'qa-history' in params['session_ids'] else {'turns': {}}
        on_result(result)
    elif method == 'agent.attach':
        turn_events.handle_turn_notification('agent.turn.event', {
            'session_id': 'qa-history', 'turn_id': 'qa-old-turn', 'seq': 0,
            'event': {'type': 'turn_end', 'status': 'completed'}})
        on_result({'ok': True})
    else:
        raise AssertionError(f'Unexpected outbound method: {method}')
replace(jsonrpc_client, 'get_jsonrpc_client', lambda: SimpleNamespace(send_request=rpc))
replace(turn_transport, 'call', rpc)
from mixar.modules.common.agent_rpc import client
replace(client, 'call', rpc)
scene = f.scene
scene.mixie_chat_messages.clear()
scene.mixie_chat_pending_attachments.clear()
scene.mixie_chat_input = ''
scene.mixie_session_id = 'qa-history'
scene.mixie_chat_user_has_engaged = True
bpy.context.window_manager.mixie_chat_is_logged_in = True
session = get_session_manager()
session.set_connected(scene)
session.set_run(scene, '', False)
message = scene.mixie_chat_messages.add()
message.sender = 'USER'
message.content = message.text = 'Keep this archived message intact.'
message.bubble_id = 'qa-history-user'
assert chat_history.archive_current(scene)
turn_events.bind(scene)
turn_events._turns['qa-old-turn'] = turn_events.Turn('qa-history', 'qa-old-turn', 'qa-run')
turn_transport.create_turn_handler(scene.name)
# Prepare the second chat with the real serializer, then switch twice using
# the real operator below. Both transcripts must survive the round trip.
scene.mixie_session_id = 'qa-other'
message.content = message.text = 'Keep the other chat too.'
assert chat_history.archive_current(scene)
scene.mixie_session_id = 'qa-history'
message.content = message.text = 'Keep this archived message intact.'
result = True
'''

SWITCH = '''
from mixar.modules.space_mixie_chat.core import turn_events, chat_history
f = drv._turn_lifecycle
with bpy.context.temp_override(window=drv.main_window()):
    assert bpy.ops.mixie_chat.open_history_session(session_id='qa-other') == {'FINISHED'}
    assert 'qa-history' in turn_events._blocked
    assert bpy.ops.mixie_chat.open_history_session(session_id='qa-history') == {'FINISHED'}
assert 'qa-history' not in turn_events._blocked
assert 'qa-other' in turn_events._blocked
assert 'qa-old-turn' not in turn_events._turns
assert f.scene.mixie_chat_messages[0].content == 'Keep this archived message intact.'
assert chat_history.load_session('qa-other')['messages'][0]['content'] == 'Keep the other chat too.'
result = True
'''

TEARDOWN = '''
from mixar.modules.space_mixie_chat.core import turn_events, turn_transport, file_handlers
from mixar.modules.space_mixie_chat.core.queue_processor import cleanup_event_queue
assert bpy.app.timers.is_registered(turn_events._drain)
cleanup_event_queue()
cleanup_event_queue()
assert not bpy.app.timers.is_registered(turn_events._drain)
file_handlers._on_load_post()
assert bpy.app.timers.is_registered(turn_events._drain)
turn_transport.create_turn_handler(drv._turn_lifecycle.scene.name)
turn_transport.cleanup_all_turn_handlers()
assert not bpy.app.timers.is_registered(turn_events._drain)
assert not turn_transport._handlers
turn_events.arm()
turn_transport.create_turn_handler(drv._turn_lifecycle.scene.name)
result = True
'''


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/turn-lifecycle'))
    out.mkdir(parents=True, exist_ok=True)
    qa.step('install_isolated_history_and_rpc', qa.eval, SETUP)
    try:
        qa.open_chat()
        qa.step('history_round_trip_preserves_both_chats', qa.eval, SWITCH)
        qa.wait("any(m.bubble_id.startswith('turn-resume-') for m in drv._turn_lifecycle.scene.mixie_chat_messages)", timeout=10)
        time.sleep(.5)
        capture(qa, out / 'history-resume-prompt.png')
        qa.step('resume_action_without_new_message', qa.eval, '''
prompt = next(m for m in drv._turn_lifecycle.scene.mixie_chat_messages
              if m.bubble_id.startswith('turn-resume-'))
with bpy.context.temp_override(window=drv.main_window()):
    result = list(bpy.ops.mixie_chat.select_slot_action(
        bubble_id=prompt.bubble_id, action_value='resume_task:qa-history'))
assert result == ['FINISHED']
''')
        qa.wait("any(t.turn_id == 'qa-old-turn' and t.complete for t in "
                "__import__('mixar.modules.space_mixie_chat.core.turn_events', fromlist=['_turns'])._turns.values())", timeout=10)
        assert qa.eval('''
from mixar.modules.space_mixie_chat.core import turn_events
assert turn_events._turns['qa-old-turn'].complete
assert turn_events._turns['qa-old-turn'].cursor == 0
result = True
''')
        time.sleep(.3)
        capture(qa, out / 'history-recovered.png')
        qa.step('timer_cleanup_and_file_load_rearm', qa.eval, TEARDOWN)
        return {'history_preserved': True, 'resumed_without_send': True,
                'timer_teardown_and_rearm': True, 'backend_calls': 0}
    finally:
        qa.eval('''
from mixar.modules.space_mixie_chat.core import chat_history
f = drv._turn_lifecycle
for module, name, value in reversed(f.originals):
    setattr(module, name, value)
chat_history.invalidate_cache()
f.scratch.cleanup()
result = True
''')


def capture(qa, path):
    qa.eval("windows=[w for w in bpy.context.window_manager.windows "
            "if any(a.type == 'AGENT_BUBBLE' and a.width > 300 for a in w.screen.areas)]\n"
            "assert windows, 'Expanded chat window must be visible'\n"
            "win=windows[0]\n"
            "with bpy.context.temp_override(window=win):\n"
            f"    result=win.mixar_qa_capture_frame(filepath={str(path)!r})")


if __name__ == '__main__':
    run_scenario('turn_lifecycle_e2e', run)
