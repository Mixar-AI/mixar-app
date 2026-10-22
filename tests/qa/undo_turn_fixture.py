# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared real-app fixture for the no-credit undo regression scenarios.

Only outbound cancellation is replaced. Scripts, routing, terminal handlers,
history ownership and undo/redo run through the installed application.
"""

import json
import os
from pathlib import Path

from lib import ensure_scenes_drawer


INSTALL = '''
from types import SimpleNamespace
from mixar.modules.space_mixie_chat.core import file_handlers
from mixar.modules.space_mixie_chat.ui.operators import session_ops
from mixar.modules.space_mixie_chat.core.executor import get_executor
assert not hasattr(drv, '_undo_turn_qa'), 'Previous undo fixture was not restored'
assert bpy.context.window_manager.mixar_per_tab_undo, 'Requires per-tab undo'
assert not get_executor()._turns, 'Use an idle isolated QA app'
assert all(not s.mixie_run_open and s.mixie_chat_state == 'IDLE'
           for s in bpy.data.scenes), 'Do not interrupt live agent work'
f = drv._undo_turn_qa = SimpleNamespace(originals=[], cancels=[])
def replace(module, name, value):
    f.originals.append((module, name, getattr(module, name)))
    setattr(module, name, value)
replace(session_ops, 'send_cancel_request_async', lambda *a: f.cancels.append(a))
replace(file_handlers, '_send_abort_request', lambda *a: f.cancels.append(a))
result = True
'''

RESTORE = '''
from mixar.modules.space_mixie_chat.core.executor import get_executor
from mixar.modules.space_mixie_chat.core.session import get_session_manager
from mixar.modules.space_mixie_chat.constants import SessionState
f = getattr(drv, '_undo_turn_qa', None)
if f is not None:
    try:
        get_executor().end_agent_turn()
        for scene in bpy.data.scenes:
            if (scene.mixie_session_id or '').startswith('qa-undo-'):
                get_session_manager().set_run(scene, '', False)
                get_session_manager().set_state(scene, SessionState.IDLE)
    finally:
        for module, name, original in reversed(f.originals):
            setattr(module, name, original)
        del drv._undo_turn_qa
result = True
'''

TURN_SETUP = '''
import json
from mixar.modules.common.agent_execution.pump import execute_request
from mixar.modules.common.agent_execution.request import ExecutionRequest
from mixar.modules.space_mixie_chat.core.executor import get_executor
from mixar.modules.space_mixie_chat.core.queue_processor import get_event_processor
from mixar.modules.space_mixie_chat.core.session import get_session_manager
from mixar.modules.space_mixie_chat.constants import SessionState
w = drv.main_window()
s = w.scene
s.mixie_session_id = 'qa-undo-' + CASE
sid, uid = s.mixie_session_id, s.session_uid
obj = next(o for o in s.objects if o.type == 'MESH')
obj.name = 'QA_UNDO_OBJECT'
obj.location.x = 0
ex = get_executor()
sm = get_session_manager()
sm.set_run(s, '', False)
sm.set_state(s, SessionState.IDLE)
def mine():
    history = json.loads(bpy.context.window_manager.mixar_undo_history)
    return [h for h in history['steps'] if h['tab_uid'] == uid]
def script(text, tool='execute_blender_code'):
    req = ExecutionRequest(request_id='qa-undo-' + CASE, script=text,
                           tool_name=tool, session_id=sid)
    reply = execute_request(req, ex)
    assert reply.get('success'), reply
    return reply
before = mine()
ex.begin_agent_turn(sid)
'''

ENDINGS = {
    'complete': 'get_event_processor()._handle_agent_complete_internal(s)',
    'stream_error': "get_event_processor()._handle_agent_error_internal('HTTP 500 QA failure', s)",
    'inband_error': "get_event_processor()._handle_inband_error('QA in-band failure', s)",
    'abort': '''
with bpy.context.temp_override(window=w):
    assert bpy.ops.mixie_chat.abort_session() == {'FINISHED'}
''',
    'refused': 'get_event_processor()._end_refused_turn(s)',
    'tab_cleanup': '''
from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import stop_scene_tab
stop_scene_tab(s, sid)
''',
    'end_all': 'ex.end_agent_turn()',
    'end_default': 'ex.end_agent_turn(sid)',
    'replay_unavailable': '''
from types import SimpleNamespace
from mixar.modules.space_mixie_chat.core.turn_events import _replay_unavailable
_replay_unavailable(s, SimpleNamespace(complete=False, pending={}, turn_id=''))
''',
    'load_pre': '''
from mixar.modules.space_mixie_chat.core.file_handlers import _on_load_pre
_on_load_pre()
''',
}

TURN_RESULT = '''
after = mine()
result = {
    'case': CASE, 'before_steps': len(before), 'after_steps': len(after),
    'delta': len(after) - len(before), 'steps': [h['name'] for h in after],
    'turns': list(ex._turns), 'x': float(obj.location.x),
    'state': s.mixie_chat_state, 'run_open': s.mixie_run_open,
    'session_id': s.mixie_session_id, 'uid': uid, 'scene': s.name,
    'cancel_requests': list(drv._undo_turn_qa.cancels),
}
'''

IDLE = '''
from mixar.modules.space_mixie_chat.core.session import get_session_manager
from mixar.modules.space_mixie_chat.constants import SessionState
s = drv.main_window().scene
get_session_manager().set_state(s, SessionState.IDLE)
get_session_manager().set_run(s, '', False)
result = True
'''


def output_dir(name):
    out = Path(os.environ.get('QA_SCENARIO_OUT', str(Path.cwd() / 'qa-out' / name)))
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_results(out, rows):
    (out / 'details.json').write_text(json.dumps(rows, indent=2) + '\n')


def reset(qa):
    # The first login establishes the startup layout that reset_state restores.
    qa.cmd('wait_login', timeout=45)
    qa.cmd('reset_state')
    qa.cmd('wait_login', timeout=45)
    ensure_scenes_drawer(qa)


def walk(qa, operation, *, tab=None, object_name='QA_UNDO_OBJECT'):
    assert operation in ('undo', 'redo')
    switch = ''
    if tab is not None:
        switch = ("from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import switch_scene_tab\n"
                  f"switch_scene_tab(bpy.data.scenes[{tab!r}])\n")
    return qa.eval(switch + f'''
w = drv.main_window()
area = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=w, area=area, region=region):
    returned = bpy.ops.ed.{operation}()
assert returned == {{'FINISHED'}}, returned
# Never retain an RNA pointer across undo: Main and its datablocks may change.
scene = drv.main_window().scene
result = {{'x': float(bpy.data.objects[{object_name!r}].location.x),
          'scene': scene.name, 'state': scene.mixie_chat_state,
          'sid': scene.mixie_session_id}}
''')


def capture(qa, path):
    qa.eval('''
w = drv.main_window()
area = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
area.spaces.active.shading.type = 'SOLID'
for obj in w.scene.objects:
    obj.select_set(obj.type == 'MESH')
with bpy.context.temp_override(window=w, area=area, region=region):
    bpy.ops.view3d.view_selected(use_all_regions=False)
    area.spaces.active.region_3d.view_distance *= 1.4
result = True
''')
    qa.snap(str(path))
