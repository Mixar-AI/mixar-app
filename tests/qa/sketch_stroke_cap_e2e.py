# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real UI regression: a 128-line sketch arrives whole, and line 129 is kept.

A drawing done one line per pause is one mark per line. The commit refused
every group past MAX_MARKS_PER_TURN (then 32), so the next line vanished as
it settled and the agent received the first 32 strokes. The cap is now 128;
past it a group joins the newest mark of the freeze, and undo takes back one
group at a time.

Run against an ISOLATED QA app launched by mixar-qa-harness/run_qa_app.sh:
  QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4781 \
    python tests/qa/sketch_stroke_cap_e2e.py

No model credits: start_stream is intercepted after the real Send operator
packs the request (same probe as scribble_send_scenario.py). Loads checkout
Python by default; SCRIBBLE_QA_INSTALLED=1 tests the built app's modules.
Review marked.png: all 129 lines visible, the pill reading "129 strokes".
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scribble_send_scenario import draw, viewport  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get('SKETCH_CAP_QA_OUT', '/tmp/mixar-sketch-stroke-cap'))
LINES = 129
CAP = 128


def setup_source(qa):
    return qa.eval('''
import importlib
import os
from pathlib import Path
from types import SimpleNamespace
assert os.environ.get('MIXAR_QA') == '1', 'Requires an isolated QA profile'
assert bpy.context.scene.mixie_chat_state == 'IDLE'
assert not bpy.context.scene.mixar_marks, 'Requires a fresh QA scene'
root = Path(SOURCE_ROOT)
for tail in ['scribble_mark.core.payload',
             'scribble_mark.core.resolve', 'scribble_mark.core.marks',
             'scribble_mark.ui.operators.mark_draw_ops']:
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
from mixar.modules.scribble_mark.core import marks, overlay, pending
from mixar.modules.scribble_mark.ui.operators import mark_draw_ops
bpy.app.driver_namespace['sketch_cap_qa_sent'] = []
bpy.app.driver_namespace['sketch_cap_qa_idle'] = mark_draw_ops.MARK_COMMIT_IDLE_S
mark_draw_ops.MARK_COMMIT_IDLE_S = 0.2
def ink():
    scene = bpy.context.scene
    held = getattr(pending._operator, '_ink', None)
    return {'marks': marks.count(scene, drafts_only=True),
            'strokes': sum(len(m.get('strokes') or []) for m in marks.draft_marks(scene)),
            'pending': len(held.strokes) if held is not None else 0,
            'settled': sum(len(g) for g in overlay._settled_strokes),
            'reading': list(overlay._reading or ())}
bpy.app.driver_namespace['sketch_cap_qa_ink'] = ink
def capture(**kwargs):
    bpy.app.driver_namespace['sketch_cap_qa_sent'].append({
        'message': kwargs.get('message'), 'mark_context': kwargs.get('mark_context'),
        'image_count': len(kwargs.get('image_attachments') or []),
    })
    return True
turn_transport.create_turn_handler = lambda **kwargs: SimpleNamespace(start_stream=capture)
result = True
'''.replace('SOURCE_ROOT', repr(str(ROOT / 'src/scripts/mixar/modules')))
       .replace('USE_INSTALLED', repr(os.environ.get('SCRIBBLE_QA_INSTALLED') == '1')))


def ink(qa):
    return qa.eval("result=bpy.app.driver_namespace['sketch_cap_qa_ink']()")


def line_at(i):
    """Short dashes on a 12 x 11 grid, clear of the pill and the hint."""
    x, y = 0.08 + (i % 12) * 0.07, 0.14 + (i // 12) * 0.06
    return (x, y), (x + 0.045, y + 0.01)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    setup_source(qa)
    try:
        qa.step('open_chat', qa.eval, "result=str(bpy.ops.mixar.bubble_restore())")
        qa.step('arm_scribble', qa.click, op='MIXAR_OT_scribble_toggle')
        qa.wait('bpy.context.window_manager.mixar_mark_armed', timeout=8)
        qa.eval("bpy.context.window_manager.mixar_mark_intent = 'SKETCH'; result = True")
        vp = viewport(qa)
        for i in range(LINES):
            start, end = line_at(i)
            qa.step(f'line_{i + 1:03d}', draw, qa, vp, start, end)
            # One pause per line: the next line must not group with this one.
            qa.wait("(lambda s: s['strokes'] == %d and s['pending'] == 0)"
                    "(bpy.app.driver_namespace['sketch_cap_qa_ink']())" % (i + 1),
                    timeout=10)
        drawn = ink(qa)
        assert drawn == {'marks': CAP, 'strokes': LINES, 'pending': 0,
                         'settled': LINES, 'reading': ['sketch', LINES]}, drawn
        qa.cmd('snap', path=str(OUT / 'marked.png'), area='VIEW_3D')

        qa.step('undo_one_line', qa.eval, "result=str(bpy.ops.mixar.scribble_mark_undo())")
        undone = ink(qa)
        assert undone == {'marks': CAP, 'strokes': LINES - 1, 'pending': 0,
                          'settled': LINES - 1, 'reading': ['sketch', LINES - 1]}, undone
        qa.cmd('snap', path=str(OUT / 'undone.png'), area='VIEW_3D')

        qa.step('send_ink_only', qa.click, op='MIXIE_CHAT_OT_send_message')
        qa.wait("len(bpy.app.driver_namespace['sketch_cap_qa_sent'])==1", timeout=10)
        context = qa.eval("result=bpy.app.driver_namespace['sketch_cap_qa_sent'][0]")['mark_context']
        assert context['intent'] == 'sketch', context['intent']
        assert len(context['marks']) == CAP, len(context['marks'])
        assert context['sketch']['stroke_count'] == LINES - 1, context['sketch']['stroke_count']
        assert len(context['sketch']['strokes']) == LINES - 1
        assert not any('joined' in m or 'strokes' in m for m in context['marks'])
        (OUT / 'request.json').write_text(json.dumps(context, indent=2))
        return {'passed': True, 'lines_drawn': LINES, 'marks': CAP,
                'strokes_after_undo': LINES - 1, 'sketch_strokes_sent': LINES - 1,
                'remote_send': False}
    finally:
        qa.eval('''
from mixar.modules.space_mixie_chat.ui.operators import chat_ops
from mixar.modules.scribble_mark.ui.operators import mark_draw_ops
from mixar.modules.scribble_mark.core import scribble_mode
from mixar.modules.space_mixie_chat.constants import SessionState
import chat_send_probe
chat_send_probe.uninstall()
mark_draw_ops.MARK_COMMIT_IDLE_S = bpy.app.driver_namespace.pop('sketch_cap_qa_idle', .6)
scribble_mode.disarm(bpy.context.window_manager)
chat_ops.get_session_manager().set_state(bpy.context.scene, SessionState.IDLE)
''')


if __name__ == '__main__':
    qa = QA()
    result = run(qa)
    (OUT / 'verdict.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
