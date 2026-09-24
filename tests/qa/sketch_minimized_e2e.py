# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sketch stays compact while accepting text; Escape previews and Enter sends.

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4791 python3 tests/qa/sketch_minimized_e2e.py
Use a fresh isolated Dev app. The only fixture replaces outgoing agent transport.
Native sketch/keyboard/pill events and rendered QA targets remain real. No credits.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from scribble_send_scenario import draw, viewport

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get('SKETCH_MINIMIZED_QA_OUT', '/tmp/mixar-sketch-minimized'))


def pill(qa, expected):
    qa.wait("bool(drv.find(surface='pill_draft_preview')) and "
            f"(drv.find_one(surface='pill_draft_preview').get('value') or '') == {expected!r}", timeout=10)
    # Hidden island uiBlocks remain in the inspection dump. The native pill
    # painter supplies this target only in its elongated minimized layout.
    assert qa.eval("w=drv.find_one(surface='pill_draft_preview')['_win']; "
                   'result=w.width > w.height * 4')
    assert qa.eval('result=bpy.context.window_manager.mixar_mark_armed')
    return qa.find(surface='pill_draft_preview')['widgets'][0]


def snap_pill(qa, name):
    qa.eval('''
w=drv.find_one(surface='pill_draft_preview')['_win']
with bpy.context.temp_override(window=w):
    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
''')
    qa.cmd('snap', path=str(OUT / f'{name}.png'),
           target={'surface':'pill_draft_preview'}, margin=100)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval('''
import os, sys
assert os.environ.get('MIXAR_QA') == '1'
assert not bpy.context.scene.mixie_chat_messages, 'Use a fresh QA scene'
sys.path.insert(0, QA_PATH)
import chat_send_probe
chat_send_probe.install()
'''.replace('QA_PATH', repr(str(ROOT / 'tests/qa'))))
    try:
        qa.eval('bpy.ops.mixar.bubble_restore()')
        qa.wait("bool(drv.find(op='MIXAR_OT_scribble_toggle'))", timeout=10)
        qa.cmd('snap', path=str(OUT / '01-expanded-before-sketch.png'),
               target={'op':'MIXAR_OT_scribble_toggle'}, margin=2500)
        qa.step('sketch_minimizes', qa.click, op='MIXAR_OT_scribble_toggle')
        assert pill(qa, '')['text'] == 'Type instructions...'
        snap_pill(qa, '02-compact-empty')
        vp = viewport(qa)
        qa.step('draw_with_compact_prompt', draw, qa, vp, (.3,.58), (.44,.72))
        qa.wait('len(bpy.context.scene.mixar_marks)==1', timeout=10)
        qa.step('type_into_minimized_pill', qa.cmd, 'type', text='Make this blue.', window=vp['window'])
        assert pill(qa, 'Make this blue.')['text'] == 'Make this blue.'
        snap_pill(qa, '03-live-draft')
        qa.cmd('press', key='RET', shift=True, window=vp['window'])
        qa.cmd('press', key='LEFT_SHIFT', window=vp['window'])
        extra = 'Keep the camera and add a small bevel to the outlined shape. '
        qa.cmd('type', text=extra, window=vp['window'])
        qa.eval('''
w=drv.main_window()
for ch in 'Café':
    drv._sim(w, type='A', value='PRESS', unicode=ch)
    drv._sim(w, type='A', value='RELEASE')
''')
        expected = 'Make this blue.\n' + extra + 'Café'
        visible = pill(qa, expected)['text']
        assert visible.startswith('...') and visible.endswith('Café'), visible
        snap_pill(qa, '04-latest-text-visible')
        qa.cmd('press', key='BACK_SPACE', window=vp['window'])
        expected = expected[:-1]
        assert pill(qa, expected)['text'].endswith('Caf')
        assert qa.eval('result=len(bpy.context.scene.mixar_marks)') == 1
        assert not qa.eval('import chat_send_probe; result=len(chat_send_probe.calls)')
        qa.step('escape_reveals_completed_preview', qa.cmd, 'press', key='ESC', window=vp['window'])
        qa.wait("not bpy.context.window_manager.mixar_mark_armed and "
                "bool(drv.find(op='MIXAR_OT_preview_sketch'))", timeout=10)
        assert qa.eval('result=bpy.context.scene.mixie_chat_input') == expected
        assert not qa.find(surface='pill_draft_preview')['widgets']
        qa.cmd('snap', path=str(OUT / '05-preview-after-escape.png'),
               target={'op':'MIXAR_OT_scribble_toggle'}, margin=2500)
        qa.step('reenter_sketch_minimizes_again', qa.click, op='MIXAR_OT_scribble_toggle')
        pill(qa, expected)
        vp = viewport(qa)
        qa.cmd('type', text='e.', window=vp['window'])
        expected += 'e.'
        pill(qa, expected)
        # Send the saved sketch directly from the minimized typing state.
        qa.step('enter_sends_from_minimized_state', qa.cmd, 'press', key='RET', window=vp['window'])
        qa.wait("len(__import__('chat_send_probe').calls)==1 and "
                'not bpy.context.window_manager.mixar_mark_armed', timeout=10)
        sent = qa.eval('''
import chat_send_probe
p=chat_send_probe.calls[-1]
s=bpy.context.scene
result={'text':p['message'], 'images':len(p.get('image_attachments') or []),
        'visible':len([m for m in s.mixie_chat_messages if m.sender=='USER'][-1].attachments),
        'draft':s.mixie_chat_input}
''')
        assert sent == {'text':expected, 'images':2, 'visible':1, 'draft':''}, sent
        qa.eval('import chat_send_probe; chat_send_probe.settle(bpy.context.scene)')
        return {'passed':True, 'automatic_minimize':True, 'live_draft':True,
                'unicode_tail_visible':True, 'backspace_keeps_ink':True,
                'escape_reveals_preview':True, 'enter_sends_while_minimized':True, 'send':sent}
    finally:
        qa.eval('''
import chat_send_probe
bpy.context.window_manager.mixar_mark_armed=False
chat_send_probe.uninstall()
''')


if __name__ == '__main__':
    verdict = run(QA())
    (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))
