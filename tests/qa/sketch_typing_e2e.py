# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Draw and type over the viewport, then send one combined sketch request.

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4791 python3 tests/qa/sketch_typing_e2e.py
Use a fresh isolated Dev app. Agent transport is a local fixture (no credits).
Keyboard, drawing, composer, preview and Send use the real app. Review the PNGs.
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
OUT = Path(os.environ.get('SKETCH_TYPING_QA_OUT', '/tmp/mixar-sketch-typing'))


def draft(qa):
    return qa.eval('result=bpy.context.scene.mixie_chat_input')


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / f'{name}.png'),
           target={'op': 'MIXAR_OT_scribble_toggle'}, margin=2500)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval('''
import os, sys
assert os.environ.get('MIXAR_QA') == '1'
assert not bpy.context.scene.mixie_chat_messages, 'Use a fresh QA scene'
sys.path.insert(0, QA_PATH)
import chat_send_probe
chat_send_probe.install()
bpy.app.driver_namespace['sketch_typing_clipboard'] = bpy.context.window_manager.clipboard
'''.replace('QA_PATH', repr(str(ROOT / 'tests/qa'))))
    try:
        qa.eval('bpy.ops.mixar.bubble_restore()')
        qa.wait("bool(drv.find(op='MIXAR_OT_scribble_toggle'))", timeout=10)
        qa.cmd('set_text', widget={'prop': 'mixie_chat_input'}, text='Please ', enter=False)
        qa.eval("drv.press(drv.find_one(prop='mixie_chat_input')['_win'], 'LEFT_SHIFT')")
        qa.click(op='MIXAR_OT_scribble_toggle')
        qa.wait('bpy.context.window_manager.mixar_mark_armed', timeout=10)
        open_controls(qa)
        vp = viewport(qa)
        qa.step('draw_before_typing', draw, qa, vp, (.3, .58), (.44, .72))
        qa.wait('len(bpy.context.scene.mixar_marks)==1', timeout=10)
        view = qa.eval('''
w=drv.main_window()
a=next(a for a in w.screen.areas if a.type=='VIEW_3D')
result=[list(row) for row in a.spaces.active.region_3d.view_matrix]
''')
        qa.step('type_over_viewport', qa.cmd, 'type', text='make this blue?', window=vp['window'])
        assert draft(qa) == 'Please make this blue?'
        qa.cmd('press', key='BACK_SPACE', window=vp['window'])
        assert draft(qa) == 'Please make this blue'
        assert qa.eval('result=len(bpy.context.scene.mixar_marks)') == 1
        qa.cmd('type', text='.', window=vp['window'])
        qa.cmd('press', key='RET', shift=True, window=vp['window'])
        qa.cmd('press', key='LEFT_SHIFT', window=vp['window'])
        # Driver's ASCII type helper has no Unicode keymap. Inject the native
        # Unicode events directly, retaining the last viewport pointer position.
        qa.eval('''
w=drv.main_window()
for ch in 'Café':
    drv._sim(w, type='A', value='PRESS', unicode=ch)
    drv._sim(w, type='A', value='RELEASE')
''')
        expected = 'Please make this blue.\nCafé'
        qa.wait('bpy.context.scene.mixie_chat_input == ' + repr(expected), timeout=5)
        qa.eval('bpy.context.window_manager.clipboard=' + repr(' style\r\nKeep the camera.\x1f'))
        qa.cmd('press', key='V', oskey=True, window=vp['window'])
        qa.cmd('press', key='OSKEY', window=vp['window'])
        expected += ' style\nKeep the camera.'
        assert draft(qa) == expected
        assert qa.eval('result=bpy.context.window_manager.mixar_mark_armed')
        assert not qa.eval('import chat_send_probe; result=len(chat_send_probe.calls)')
        assert view == qa.eval('''
a=next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')
result=[list(row) for row in a.spaces.active.region_3d.view_matrix]
''')
        snap(qa, '01-typed-while-sketching')
        qa.cmd('snap', path=str(OUT / '02-viewport-typing-hint.png'), area='VIEW_3D')
        qa.step('undo_ink_keeps_text', qa.cmd, 'press', key='Z', ctrl=True, window=vp['window'])
        qa.cmd('press', key='LEFT_CTRL', window=vp['window'])
        qa.wait('len(bpy.context.scene.mixar_marks)==0', timeout=10)
        assert draft(qa) == expected
        qa.step('draw_again_after_typing', draw, qa, vp, (.3, .58), (.44, .72))
        qa.wait('len(bpy.context.scene.mixar_marks)==1', timeout=10)
        qa.click(op='MIXAR_OT_scribble_toggle')
        qa.wait('not bpy.context.window_manager.mixar_mark_armed and '
                'len(bpy.context.scene.mixie_chat_pending_attachments)==1', timeout=10)
        assert draft(qa) == expected
        snap(qa, '03-preview-with-instructions')
        # Click-to-edit after viewport typing must preserve the new draft.
        qa.click(prop='mixie_chat_input')
        qa.cmd('press', key='END', window=qa.find(prop='mixie_chat_input')['widgets'][0]['window'])
        qa.click(op='MIXIE_CHAT_OT_send_message')
        qa.wait('bool(__import__("chat_send_probe").calls)', timeout=10)
        sent = qa.eval('''
import chat_send_probe
c=chat_send_probe.calls[-1]
s=bpy.context.scene
result={'text':c['message'], 'wire_images':len(c.get('image_attachments') or []),
        'visible_images':len([m for m in s.mixie_chat_messages if m.sender=='USER'][-1].attachments),
        'marks':len(s.mixar_marks), 'draft':s.mixie_chat_input}
''')
        assert sent == {'text':expected, 'wire_images':2, 'visible_images':1,
                        'marks':1, 'draft':''}, sent
        qa.eval('import chat_send_probe; chat_send_probe.settle(bpy.context.scene)')
        return {'passed': True, 'viewport_typing': True, 'unicode': True,
                'backspace_keeps_ink': True, 'paste_and_shift_enter_do_not_send': True,
                'undo_ink_keeps_text': True, 'view_stays_frozen': True, 'send':sent}
    finally:
        qa.eval('''
import chat_send_probe
bpy.context.window_manager.mixar_mark_armed=False
bpy.context.window_manager.clipboard=bpy.app.driver_namespace.pop('sketch_typing_clipboard')
chat_send_probe.uninstall()
''')


if __name__ == '__main__':
    verdict = run(QA())
    (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))
