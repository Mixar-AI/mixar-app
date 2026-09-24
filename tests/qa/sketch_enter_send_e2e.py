# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Viewport Enter sends text and pending sketch ink; Shift+Enter adds a line.

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4791 python3 tests/qa/sketch_enter_send_e2e.py
Requires a fresh isolated Dev app. Only agent transport is a fixture (no credits).
Review the before/after screenshots alongside the state assertions.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from scribble_send_scenario import draw, viewport
from sketch_controls import open_controls

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get('SKETCH_ENTER_QA_OUT', '/tmp/mixar-sketch-enter'))


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / f'{name}.png'),
           target={'op': 'MIXAR_OT_scribble_toggle'}, margin=2500)


def sent_state(qa):
    return qa.eval('''
import chat_send_probe
s=bpy.context.scene
p=chat_send_probe.calls[-1]
users=[m for m in s.mixie_chat_messages if m.sender=='USER']
result={'text':p['message'], 'calls':len(chat_send_probe.calls),
        'images':len(p.get('image_attachments') or []),
        'visible':len(users[-1].attachments), 'marks':len(p['mark_context']['marks']),
        'pending':len(s.mixie_chat_pending_attachments), 'draft':s.mixie_chat_input,
        'armed':bpy.context.window_manager.mixar_mark_armed}
''')


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval('''
import os, sys
assert os.environ.get('MIXAR_QA') == '1'
assert not bpy.context.scene.mixie_chat_messages, 'Use a fresh QA scene'
sys.path.insert(0, QA_PATH)
import chat_send_probe
chat_send_probe.install()
from mixar.modules.scribble_mark.ui.operators import mark_draw_ops
bpy.app.driver_namespace['sketch_enter_idle'] = mark_draw_ops.MARK_COMMIT_IDLE_S
mark_draw_ops.MARK_COMMIT_IDLE_S = 300.0
'''.replace('QA_PATH', repr(str(ROOT / 'tests/qa'))))
    try:
        qa.eval('bpy.ops.mixar.bubble_restore()')
        qa.wait("bool(drv.find(op='MIXAR_OT_scribble_toggle'))", timeout=10)
        qa.click(op='MIXAR_OT_scribble_toggle')
        qa.wait('bpy.context.window_manager.mixar_mark_armed', timeout=10)
        open_controls(qa)
        vp = viewport(qa)
        qa.step('draw_pending_ink', draw, qa, vp, (.3, .58), (.44, .72))
        qa.cmd('type', text='Make this blue.', window=vp['window'])
        qa.step('shift_enter_adds_line', qa.cmd, 'press', key='RET', shift=True, window=vp['window'])
        qa.cmd('press', key='LEFT_SHIFT', window=vp['window'])
        qa.cmd('type', text='Keep the camera.', window=vp['window'])
        expected = 'Make this blue.\nKeep the camera.'
        assert qa.eval('result=bpy.context.scene.mixie_chat_input') == expected
        assert qa.eval('result=len(bpy.context.scene.mixar_marks)') == 0
        assert not qa.eval('import chat_send_probe; result=len(chat_send_probe.calls)')
        snap(qa, '01-ready-for-enter')
        qa.eval('import chat_send_probe; chat_send_probe.connected=False')
        qa.step('disconnected_enter', qa.cmd, 'press', key='RET', window=vp['window'])
        qa.wait("bool(drv.find(text='Not connected to server', popup=True))", timeout=10)
        assert qa.eval('result=bpy.context.scene.mixie_chat_input') == expected
        assert qa.eval('result=bpy.context.window_manager.mixar_mark_armed')
        assert qa.eval('result=len(bpy.context.scene.mixar_marks)') == 1
        assert not qa.eval('import chat_send_probe; result=len(chat_send_probe.calls)')
        popup = qa.find(text='Not connected to server', popup=True)['widgets'][0]
        qa.cmd('press', key='ESC', window=popup['window'])
        qa.wait('not drv.find(popup=True)', timeout=5)
        qa.eval('import chat_send_probe; chat_send_probe.connected=True')
        # A second, still-pending stroke must make the successful request.
        qa.step('draw_final_pending_stroke', draw, qa, vp, (.44, .72), (.55, .58))
        assert qa.eval('result=len(bpy.context.scene.mixar_marks)') == 1
        qa.step('enter_sends_text_and_ink', qa.cmd, 'press', key='RET', window=vp['window'])
        qa.wait("len(__import__('chat_send_probe').calls)==1 and "
                'not bpy.context.window_manager.mixar_mark_armed', timeout=10)
        first = sent_state(qa)
        assert first == {'text':expected, 'calls':1, 'images':2, 'visible':1,
                         'marks':2, 'pending':0, 'draft':'', 'armed':False}, first
        qa.eval('import chat_send_probe; chat_send_probe.settle(bpy.context.scene)')
        # The turn checkpoint closes the old island and recreates its pill on
        # a timer. Restore is a no-op until that native window exists.
        qa.wait("bool(drv.find(text='Mixie', area_type='AGENT_BUBBLE', "
                "region_type='HEADER'))", timeout=10)
        qa.eval('bpy.ops.mixar.bubble_restore()')
        qa.wait("bool(drv.find(op='MIXAR_OT_scribble_toggle'))", timeout=10)
        qa.eval('''
w=drv.find_one(op='MIXAR_OT_scribble_toggle')['_win']
with bpy.context.temp_override(window=w):
    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
''')
        snap(qa, '02-sent-with-enter')
        qa.click(op='MIXAR_OT_scribble_toggle')
        qa.wait('bpy.context.window_manager.mixar_mark_armed', timeout=10)
        open_controls(qa)
        qa.cmd('choose', widget={'op':'WM_OT_context_menu_enum', 'area_type':'AGENT_BUBBLE'},
               item='Draw to build')
        vp = viewport(qa)
        draw(qa, vp, (.3, .55), (.55, .55))
        qa.step('numpad_enter_sends_sketch_only', qa.cmd, 'press', key='NUMPAD_ENTER', window=vp['window'])
        qa.wait("len(__import__('chat_send_probe').calls)==2 and "
                'not bpy.context.window_manager.mixar_mark_armed', timeout=10)
        second = sent_state(qa)
        assert second == {'text':'Build what I drew in this sketch.', 'calls':2,
                          'images':2, 'visible':1, 'marks':1, 'pending':0,
                          'draft':'', 'armed':False}, second
        qa.eval('import chat_send_probe; chat_send_probe.settle(bpy.context.scene)')
        return {'passed':True, 'shift_enter_newline':True, 'refused_enter_preserves_draft':True,
                'pending_ink_flushed':True, 'enter':first, 'numpad_enter_sketch_only':second}
    finally:
        qa.eval('''
import chat_send_probe
from mixar.modules.scribble_mark.ui.operators import mark_draw_ops
mark_draw_ops.MARK_COMMIT_IDLE_S=bpy.app.driver_namespace.pop('sketch_enter_idle')
bpy.context.window_manager.mixar_mark_armed=False
chat_send_probe.uninstall()
''')


if __name__ == '__main__':
    verdict = run(QA())
    (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))
