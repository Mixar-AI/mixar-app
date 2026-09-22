# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real UI regression: visible ink, exclusive input, and a complete sketch send.

Run against an ISOLATED QA app launched by mixar-qa-harness/run_qa_app.sh:
  QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4781 \
    python tests/qa/scribble_send_scenario.py

No model credits: intercept start_stream after the real Send operator packs
the request. Auth headers and image bytes never enter the captured artifact.
Loads checkout Python by default. SCRIBBLE_QA_INSTALLED=1 tests the built app
without replacing its modules. No C++ changes.
The screenshots still require visual review. This does not test model quality.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get('SCRIBBLE_QA_OUT', '/tmp/mixar-scribble-send'))


def setup_source(qa):
    return qa.eval('''
import importlib
import os
from pathlib import Path
from types import SimpleNamespace
assert os.environ.get('MIXAR_QA') == '1', 'Requires an isolated QA profile'
assert bpy.context.scene.mixie_chat_state == 'IDLE'
assert not bpy.context.scene.mixie_chat_messages, 'Requires a fresh QA scene'
assert not bpy.context.scene.mixar_marks, 'Requires a fresh QA scene'
root = Path(SOURCE_ROOT)
core = importlib.import_module('mixar.modules.scribble_mark.core')
if not USE_INSTALLED:
    core.__path__.insert(0, str(root / 'scribble_mark/core'))
for tail in ['scribble_mark.core.freeze_session', 'scribble_mark.core.chat_bridge',
             'scribble_mark.ui.operators.mark_draw_ops',
             'space_mixie_chat.ui.operators.chat_ops']:
    if USE_INSTALLED:
        continue
    module = importlib.import_module('mixar.modules.' + tail)
    for cls in getattr(module, 'classes', ()):
        bpy.utils.unregister_class(cls)
    path = root.joinpath(*tail.split('.')).with_suffix('.py')
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), 'exec'), module.__dict__)
    for cls in getattr(module, 'classes', ()):
        bpy.utils.register_class(cls)
import sys
sys.path.insert(0, str(root.parents[3] / 'tests/qa'))
import chat_send_probe
chat_send_probe.install()
from mixar.modules.space_mixie_chat.core import turn_transport
bpy.app.driver_namespace['scribble_qa_sent'] = []
def capture(**kwargs):
    bpy.app.driver_namespace['scribble_qa_sent'].append({
        'message': kwargs.get('message'), 'mark_context': kwargs.get('mark_context'),
        'attachment_names': kwargs.get('attachment_names'),
        'image_count': len(kwargs.get('image_attachments') or []),
    })
    return True
turn_transport.create_turn_handler = lambda **kwargs: SimpleNamespace(start_stream=capture)
result = True
'''.replace('SOURCE_ROOT', repr(str(ROOT / 'src/scripts/mixar/modules')))
       .replace('USE_INSTALLED', repr(os.environ.get('SCRIBBLE_QA_INSTALLED') == '1')))


def viewport(qa):
    return qa.eval('''
win=drv.main_window()
area=max((a for a in win.screen.areas if a.type=='VIEW_3D'), key=lambda a:a.width*a.height)
region=next(r for r in area.regions if r.type=='WINDOW')
result={'window':win.as_pointer(), 'x':region.x,'y':region.y,'w':region.width,'h':region.height}
''')


def draw(qa, vp, start, end, button='LEFTMOUSE'):
    def point(uv):
        return {'window': vp['window'], 'x': vp['x'] + int(uv[0] * vp['w']),
                'y': vp['y'] + int(uv[1] * vp['h'])}
    return qa.cmd('drag', **{'from': point(start), 'to': point(end), 'steps': 12, 'button': button})


def drawer_state(qa):
    return qa.eval("""
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'TOOL_PROPS')
wm = bpy.context.window_manager
result = {'amount': wm.mixar_moodboard_drawer_amount,
          'target': wm.mixar_moodboard_drawer_target,
          'width': wm.mixar_moodboard_drawer_width,
          'origin': r.view2d.region_to_view(100, 100),
          'extent': r.view2d.region_to_view(200, 200)}
""")


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    setup_source(qa)
    try:
        qa.step('open_chat', qa.eval, "result=str(bpy.ops.mixar.bubble_restore())")
        qa.step('open_moodboard', qa.click, surface='moodboard_drawer_grip')
        qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount == 1', timeout=8)
        drawer = drawer_state(qa)
        qa.cmd('snap', path=str(OUT / 'before.png'))
        qa.step('arm_then_escape', qa.click, op='MIXAR_OT_scribble_toggle')
        qa.wait('bpy.context.window_manager.mixar_mark_armed and '
                'bpy.context.window_manager.mixar_moodboard_drawer_amount == 0', timeout=8)
        qa.cmd('press', key='ESC', window=viewport(qa)['window'])
        qa.wait('not bpy.context.window_manager.mixar_mark_armed', timeout=8)
        assert drawer_state(qa) == drawer, 'Esc must restore the original moodboard view'
        qa.step('reopen_chat_after_escape', qa.eval, "result=str(bpy.ops.mixar.bubble_restore())")
        qa.step('arm_scribble', qa.click, op='MIXAR_OT_scribble_toggle')
        qa.wait('bpy.context.window_manager.mixar_mark_armed', timeout=8)
        vp = viewport(qa)
        assert drawer_state(qa)['amount'] == 0, 'The drawing surface must be unobstructed'
        frozen = qa.eval('''
a = next(a for a in drv.main_window().screen.areas if a.type == 'VIEW_3D')
v = a.spaces.active.region_3d
result = [list(v.view_rotation), list(v.view_location), v.view_distance]
''')
        qa.step('pan_is_blocked', draw, qa, vp, (.86, .6), (.92, .5), 'MIDDLEMOUSE')
        after_pan = qa.eval('''
a = next(a for a in drv.main_window().screen.areas if a.type == 'VIEW_3D')
v = a.spaces.active.region_3d
result = [list(v.view_rotation), list(v.view_location), v.view_distance]
''')
        assert after_pan == frozen, 'A Scribble drag must not navigate the view'
        qa.step('first_stroke', draw, qa, vp, (.35, .4), (.55, .62))
        qa.wait('len(bpy.context.scene.mixar_marks)==1', timeout=10)
        qa.step('choose_sketch', qa.cmd, 'choose',
                widget={'op': 'WM_OT_context_menu_enum', 'area_type': 'AGENT_BUBBLE'}, item='Draw to build')
        # Hold the timer so screenshots/harness latency cannot hide the race.
        qa.eval('''
from mixar.modules.scribble_mark.ui.operators import mark_draw_ops
bpy.app.driver_namespace['scribble_qa_idle'] = mark_draw_ops.MARK_COMMIT_IDLE_S
mark_draw_ops.MARK_COMMIT_IDLE_S = 300.0
''')
        qa.step('pending_final_stroke', draw, qa, vp, (.86, .42), (.94, .60))
        before = qa.eval('''
from mixar.modules.scribble_mark.core import pending
result={'stored':len(bpy.context.scene.mixar_marks),'pending':len(pending._operator._ink.strokes),
        'input':bpy.context.scene.mixie_chat_input,'reading':bpy.context.window_manager.mixar_mark_intent}
''')
        assert before == {'stored': 1, 'pending': 1, 'input': '', 'reading': 'SKETCH'}, before
        qa.cmd('snap', path=str(OUT / 'marked.png'))
        qa.cmd('snap', path=str(OUT / 'pad.png'), target={'op': 'MIXAR_OT_scribble_toggle'}, margin=3000)
        qa.step('send_ink_only', qa.click, op='MIXIE_CHAT_OT_send_message')
        qa.wait("len(bpy.app.driver_namespace['scribble_qa_sent'])==1", timeout=10)
        qa.wait('not bpy.context.window_manager.mixar_mark_armed and '
                'not bpy.context.window_manager.mixie_chat_ink_visible', timeout=8)
        sent = qa.eval("result=bpy.app.driver_namespace['scribble_qa_sent']")
        payload = sent[0]
        assert payload['message'].endswith('Build what I drew in this sketch.'), payload['message']
        assert payload['mark_context']['intent'] == 'sketch'
        assert payload['mark_context']['intent_source'] == 'user'
        assert len(payload['mark_context']['marks']) == 2
        assert payload['mark_context']['sketch']['stroke_count'] == 2
        assert payload['image_count'] == 2 and len(payload['attachment_names']) == 2
        assert all(n.startswith('mixar_mark_frame') for n in payload['attachment_names'])
        states = qa.eval('result=[m.state for m in bpy.context.scene.mixar_marks]')
        assert states == ['SENT', 'SENT'], states
        assert drawer_state(qa) == drawer, 'Send must restore the unchanged moodboard view'
        qa.cmd('snap', path=str(OUT / 'restored.png'), area='VIEW_3D')
        qa.cmd('snap', path=str(OUT / 'sent.png'), target={'op': 'MIXIE_CHAT_OT_abort_session'}, margin=3000)
        (OUT / 'request.json').write_text(json.dumps(payload, indent=2))
        return {'passed': True, 'marks': 2, 'strokes': 2, 'images': 2,
                'empty_composer': True, 'disarmed': True, 'remote_send': False,
                'moodboard_restored_after_escape_and_send': True}
    finally:
        qa.eval('''
from mixar.modules.space_mixie_chat.ui.operators import chat_ops
from mixar.modules.scribble_mark.ui.operators import mark_draw_ops
from mixar.modules.scribble_mark.core import scribble_mode
from mixar.modules.space_mixie_chat.constants import SessionState
import chat_send_probe
chat_send_probe.uninstall()
mark_draw_ops.MARK_COMMIT_IDLE_S = bpy.app.driver_namespace.pop('scribble_qa_idle', .6)
scribble_mode.disarm(bpy.context.window_manager)
chat_ops.get_session_manager().set_state(bpy.context.scene, SessionState.IDLE)
''')


if __name__ == '__main__':
    qa = QA()
    result = run(qa)
    (OUT / 'verdict.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
