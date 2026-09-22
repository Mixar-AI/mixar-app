# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Separate annotation, typing, Voice and explicit Handwriting in the real app.

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4787 python3 tests/qa/scribble_input_modes_e2e.py
Requires a fresh isolated app built from this checkout. No paid requests:
only microphone/voice transport and outgoing agent transport are fixtures.
Native events, real operators, draft ownership and mark packing remain live.
Inspect the screenshots; this does not prove microphone or recognizer accuracy.
"""
import inspect
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from scribble_send_scenario import draw, viewport
from sketch_controls import open_controls

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get('SCRIBBLE_QA_OUT', '/tmp/mixar-scribble-input-modes'))


def install_voice_fixture():
    import aud
    import bpy
    import queue
    from mixar.modules.space_mixie_chat.core import voice
    from mixar.modules.space_mixie_chat.core.voice_input import transport
    voice.cancel()
    saved = {name: getattr(aud, name) for name in (
        '_mixar_capture_permission', '_mixar_capture_open',
        '_mixar_capture_read', '_mixar_capture_stop')}
    bpy.app.driver_namespace['scribble_voice_saved'] = (saved, transport.Transport)

    class LocalDictation:
        def __init__(self, *args):
            self.events = queue.Queue()
            self.timings = {}
            self.cancelled = False
        def start(self):
            self.events.put({'type': 'ready', 'max_duration_seconds': 180})
        def feed(self, data):
            pass
        def stop(self):
            def final():
                if not self.cancelled:
                    self.events.put({'type': 'final', 'text': 'Keep the camera.'})
            bpy.app.timers.register(final, first_interval=0.5)
        def cancel(self):
            self.cancelled = True
    transport.Transport = LocalDictation
    aud._mixar_capture_permission = lambda: 1
    aud._mixar_capture_open = lambda: object()
    aud._mixar_capture_read = lambda handle: b'\0' * 640
    aud._mixar_capture_stop = lambda handle: b''


def flags(qa):
    return qa.eval('''
w = bpy.context.window_manager
result = {'marks':w.mixar_mark_armed, 'ink':w.mixie_chat_ink_visible,
          'voice':w.mixie_chat_voice_listening}
''')


def geometry(qa):
    return qa.eval('''
w = next(w for w in bpy.context.window_manager.windows
         if any(a.type == 'AGENT_BUBBLE' and any(r.type == 'TOOLS' for r in a.regions)
                for a in w.screen.areas))
result = [w.width, w.height]
''')


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / f'{name}.png'),
           target={'op': 'MIXAR_OT_scribble_toggle'}, margin=2500)


def type_prompt(qa, text):
    qa.cmd('set_text', widget={'prop': 'mixie_chat_input', 'area_type': 'AGENT_BUBBLE'},
           text=text, enter=False)
    qa.eval("drv.press(drv.find_one(prop='mixie_chat_input')['_win'], 'LEFT_SHIFT')")


def assert_chip_geometry(qa):
    """No overlapping hit targets in the actual native layout."""
    controls = qa.find(area_type='AGENT_BUBBLE', region_type='TOOLS')['widgets']
    ops = {'MIXAR_OT_scribble_toggle', 'MIXIE_CHAT_OT_voice_toggle',
           'MIXIE_CHAT_OT_toggle_auto_mode', 'MIXIE_CHAT_OT_send_message',
           'MIXAR_OT_scribble_mark_clear', 'WM_OT_context_menu_enum',
           'MIXIE_CHAT_OT_add_image_from_file'}
    rects = [w['rect'] for w in controls if w.get('op') in ops]
    for i, a in enumerate(rects):
        for b in rects[i+1:]:
            assert min(a[2], b[2]) <= max(a[0], b[0]) or min(a[3], b[3]) <= max(a[1], b[1]), (a, b)




def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval('''
import sys
assert __import__('os').environ.get('MIXAR_QA') == '1'
assert not bpy.context.scene.mixie_chat_messages, 'Use a fresh QA scene'
sys.path.insert(0, QA_PATH)
import chat_send_probe
chat_send_probe.install()
'''.replace('QA_PATH', repr(str(ROOT / 'tests/qa'))))
    qa.eval(inspect.getsource(install_voice_fixture) + '\ninstall_voice_fixture()')
    try:
        qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
        qa.wait("bool(drv.find(op='MIXIE_CHAT_OT_ink_toggle'))", timeout=10)
        normal = geometry(qa)
        snap(qa, '01-default')
        qa.step('annotation_only', qa.click, op='MIXAR_OT_scribble_toggle')
        qa.wait('bpy.context.window_manager.mixar_mark_armed', timeout=10)
        open_controls(qa)
        assert flags(qa) == {'marks': True, 'ink': False, 'voice': False}
        assert geometry(qa) == normal, 'Annotation must not resize the composer'
        assert qa.find(prop='mixie_chat_input')['widgets']
        qa.step('type_while_annotating', type_prompt, qa, 'Make this blue.')
        vp = viewport(qa)
        qa.step('draw_annotation', draw, qa, vp, (.3, .56), (.48, .68))
        qa.wait('len(bpy.context.scene.mixar_marks) == 1', timeout=10)
        assert flags(qa)['marks'] and not flags(qa)['ink']
        assert_chip_geometry(qa)
        snap(qa, '02-annotate-and-type')
        qa.cmd('snap', path=str(OUT / '03-viewport-mark.png'), area='VIEW_3D')
        qa.step('voice_while_annotating', qa.click, op='MIXIE_CHAT_OT_voice_toggle')
        qa.wait("bpy.context.window_manager.mixie_chat_voice_status == 'Listening'", timeout=10)
        assert flags(qa) == {'marks': True, 'ink': False, 'voice': True}
        assert_chip_geometry(qa)
        snap(qa, '04-annotate-and-voice')
        qa.step('stop_voice', qa.click, op='MIXIE_CHAT_OT_voice_toggle')
        qa.wait('not bpy.context.window_manager.mixie_chat_voice_listening', timeout=10)
        text = qa.eval('result=bpy.context.scene.mixie_chat_input')
        assert text == 'Make this blue. Keep the camera.', text
        assert flags(qa)['marks']
        assert not qa.eval('import chat_send_probe; result=len(chat_send_probe.calls)'), 'Stop must not send'
        qa.step('explicit_handwriting', qa.click, op='MIXIE_CHAT_OT_ink_toggle')
        qa.wait('bpy.context.window_manager.mixie_chat_ink_visible', timeout=10)
        assert flags(qa)['marks']
        assert_chip_geometry(qa)
        snap(qa, '05-explicit-handwriting')
        qa.step('close_handwriting_keep_annotation', qa.click, op='MIXIE_CHAT_OT_ink_toggle')
        qa.wait('not bpy.context.window_manager.mixie_chat_ink_visible', timeout=10)
        assert flags(qa)['marks']
        assert geometry(qa) == normal
        assert qa.eval('result=bpy.context.scene.mixie_chat_input') == text
        composer = qa.find(prop='mixie_chat_input', area_type='AGENT_BUBBLE')['widgets'][0]
        qa.cmd('type', text=' Add a bevel.', window=composer['window'])
        text += ' Add a bevel.'
        assert qa.eval('result=bpy.context.scene.mixie_chat_input') == text
        qa.step('reopen_handwriting', qa.click, op='MIXIE_CHAT_OT_ink_toggle')
        qa.wait('bpy.context.window_manager.mixie_chat_ink_visible', timeout=10)
        qa.step('close_annotation_keep_handwriting', qa.click, op='MIXAR_OT_scribble_toggle')
        qa.wait('not bpy.context.window_manager.mixar_mark_armed', timeout=10)
        assert flags(qa)['ink']
        qa.click(op='MIXIE_CHAT_OT_ink_toggle')
        qa.wait('not bpy.context.window_manager.mixie_chat_ink_visible', timeout=10)
        qa.click(op='MIXAR_OT_scribble_toggle')
        qa.wait('bpy.context.window_manager.mixar_mark_armed', timeout=10)
        open_controls(qa)
        scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
        qa.eval('bpy.context.preferences.view.ui_scale=1.25')
        assert_chip_geometry(qa)
        snap(qa, '05b-annotate-125-percent')
        qa.eval(f'bpy.context.preferences.view.ui_scale={scale!r}')
        qa.eval('''from mixar.modules.scribble_mark.ui.operators import mark_draw_ops
bpy.app.driver_namespace['scribble_idle_saved']=mark_draw_ops.MARK_COMMIT_IDLE_S
mark_draw_ops.MARK_COMMIT_IDLE_S=300.0''')
        qa.step('pending_mark_before_send', draw, qa, viewport(qa), (.26,.6), (.40,.72))
        assert qa.eval('from mixar.modules.scribble_mark.core import pending; result=not pending._operator._ink.empty')
        qa.step('send_combined_prompt', qa.click, op='MIXIE_CHAT_OT_send_message')
        qa.wait("len(__import__('chat_send_probe').calls) == 1", timeout=10)
        qa.wait('not bpy.context.window_manager.mixar_mark_armed', timeout=10)
        payload = qa.eval('''
import chat_send_probe
p=chat_send_probe.calls[0]
result={'message':p['message'],'mark_count':len(p['mark_context']['marks']),
        'image_count':len(p.get('image_attachments') or [])}
''')
        assert payload['message'].endswith(text), payload
        assert payload['mark_count'] == 2 and payload['image_count'] == 4, payload
        # Each frozen view has one annotated preview; clean companions are agent-only.
        visible = qa.eval("result=[len(m.attachments) for m in bpy.context.scene.mixie_chat_messages "
                          "if m.sender=='USER']")
        assert visible == [2], visible
        assert flags(qa) == {'marks': False, 'ink': False, 'voice': False}
        qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
        qa.wait("bool(drv.find(op='MIXAR_OT_scribble_toggle'))", timeout=10)
        snap(qa, '06-sent')
        return {'passed': True, 'voice': 'local capture/transport fixture',
                'paid_requests': 0, 'payload': payload, 'steps': qa.log}
    finally:
        qa.eval('''
from mixar.modules.space_mixie_chat.core import voice
from mixar.modules.space_mixie_chat.core.voice_input import transport
from mixar.modules.scribble_mark.core import scribble_mode
voice.cancel()
from mixar.modules.scribble_mark.ui.operators import mark_draw_ops
mark_draw_ops.MARK_COMMIT_IDLE_S=bpy.app.driver_namespace.pop('scribble_idle_saved',.6)
import aud
saved, original = bpy.app.driver_namespace.pop('scribble_voice_saved')
for name, fn in saved.items(): setattr(aud, name, fn)
transport.Transport = original
scribble_mode.disarm(bpy.context.window_manager)
import chat_send_probe
chat_send_probe.uninstall()
''')


if __name__ == '__main__':
    qa = QA()
    result = {'passed': False}
    try:
        result = run(qa)
    finally:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / 'verdict.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
