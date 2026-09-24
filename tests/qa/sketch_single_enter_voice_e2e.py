# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""One Enter after viewport typing; hold-Option/Alt dictation without leaving Sketch.

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4791 python3 tests/qa/sketch_single_enter_voice_e2e.py
Fresh isolated Dev scene. Real UI/operators; capture and transports are fixtures.
No microphone recording or paid requests. Review the screenshots and verdict.
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
OUT = Path(os.environ.get('SKETCH_SINGLE_ENTER_QA_OUT', '/tmp/mixar-sketch-single-enter'))


def restore(qa, after_send=False):
    if after_send:
        qa.wait("bool(drv.find(text='Mixie', area_type='AGENT_BUBBLE', region_type='HEADER'))", timeout=10)
    qa.eval('bpy.ops.mixar.bubble_restore()')
    qa.wait("bool(drv.find(op='MIXAR_OT_scribble_toggle'))", timeout=10)


def hover_composer(qa):
    # Typing in the viewport released text editing. A real pointer move into
    # the field highlights it without a click; Enter used to only activate it.
    qa.eval("w=drv.find_one(prop='mixie_chat_input'); r=w['rect']; "
            "drv.move_to(w['_win'], int((r[0]+r[2])/2), int((r[1]+r[3])/2))")
    widget = qa.find(prop='mixie_chat_input')['widgets'][0]
    assert not widget.get('text_edit'), widget
    return widget['window']


def snap(qa, name, target):
    qa.eval(f"w=drv.find_one(**{target!r})['_win']\n"
            "with bpy.context.temp_override(window=w):\n"
            "    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)")
    qa.cmd('snap', path=str(OUT / f'{name}.png'), target=target, margin=2000)


def assert_sent(qa, text, count):
    qa.wait(f"len(__import__('chat_send_probe').calls)=={count} and "
            'not bpy.context.window_manager.mixar_mark_armed', timeout=10)
    actual = qa.eval('''
import chat_send_probe
s=bpy.context.scene
p=chat_send_probe.calls[-1]
result={'text':p['message'], 'wire':len(p.get('image_attachments') or []),
        'visible':len([m for m in s.mixie_chat_messages if m.sender=='USER'][-1].attachments),
        'draft':s.mixie_chat_input}
chat_send_probe.settle(s)
''')
    assert actual == {'text':text, 'wire':2, 'visible':1, 'draft':''}, actual
    return actual


def talk_key(qa, vp, value):
    """Hold (PRESS) or release left Option/Alt over the frozen viewport.

    Separate native events, because push-to-talk starts only after the key
    has been held alone for HOLD_SECONDS; a PRESS+RELEASE pair is a tap.
    """
    qa.eval("w=drv.main_window()\n"
            f"drv.move_to(w, {vp['x'] + vp['w'] // 2}, {vp['y'] + vp['h'] // 3})\n"
            f"drv._sim(w, type='LEFT_ALT', value={value!r})\nresult=True")


def tap_does_not_talk(qa, vp):
    talk_key(qa, vp, 'PRESS')
    talk_key(qa, vp, 'RELEASE')
    qa.wait(f"__import__('time').monotonic() >= {__import__('time').monotonic() + 0.6}", timeout=3)
    assert not qa.eval('result=bpy.context.window_manager.mixie_chat_voice_status')
    return True


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval('''
import os, sys
assert os.environ.get('MIXAR_QA') == '1'
assert not bpy.context.scene.mixie_chat_messages, 'Use a fresh QA scene'
sys.path.insert(0, QA_PATH)
import chat_send_probe, voice_focus_probe
chat_send_probe.install()
voice_focus_probe.install()
'''.replace('QA_PATH', repr(str(ROOT / 'tests/qa'))))
    results = []
    try:
        for i, key in enumerate(('RET', 'NUMPAD_ENTER')):
            restore(qa, after_send=bool(i))
            qa.click(op='MIXAR_OT_scribble_toggle')
            open_controls(qa)
            vp = viewport(qa)
            draw(qa, vp, (.3,.58), (.44,.72))
            text = 'Vary the bevel.'
            qa.cmd('type', text=text, window=vp['window'])
            assert qa.eval('result=bpy.context.scene.mixie_chat_input') == text
            win = hover_composer(qa)
            if i == 0:
                # Shift+Enter must also work on the first activating press.
                qa.cmd('press', key='RET', shift=True, window=win)
                qa.cmd('press', key='LEFT_SHIFT', window=win)
                assert qa.eval('result=bpy.context.scene.mixie_chat_input') == text + '\n'
                assert not qa.eval("result=len(__import__('chat_send_probe').calls)")
                qa.cmd('type', text='Keep the camera.', window=vp['window'])
                text += '\nKeep the camera.'
                win = hover_composer(qa)
                snap(qa, '01-hovered-draft', {'prop':'mixie_chat_input'})
            qa.step(f'one_{key}_sends_from_hover', qa.cmd, 'press', key=key, window=win)
            results.append(assert_sent(qa, text, i+1))
        restore(qa, after_send=True)
        qa.click(op='MIXAR_OT_scribble_toggle')
        qa.wait("bool(drv.find(surface='pill_draft_preview'))", timeout=10)
        vp = viewport(qa)
        draw(qa, vp, (.3,.58), (.44,.72))
        qa.cmd('type', text='Vivid bevels.', window=vp['window'])
        qa.wait('any(m.state=="DRAFT" for m in bpy.context.scene.mixar_marks)', timeout=10)
        qa.cmd('snap', path=str(OUT / '01b-voice-shortcut.png'), area='VIEW_3D')
        qa.step('tap_does_not_talk', tap_does_not_talk, qa, vp)
        qa.step('hold_option_alt_starts_voice', talk_key, qa, vp, 'PRESS')
        qa.wait("bpy.context.window_manager.mixie_chat_voice_status=='Listening'", timeout=10)
        assert qa.eval('result=bpy.context.scene.mixie_chat_input') == 'Vivid bevels.'
        assert qa.find(surface='pill_draft_preview')['widgets']
        # The window's current frame, no forced redraw: the hint must repaint
        # itself when the voice status changes ('snap' can reuse a stale buffer).
        qa.wait(f"__import__('time').monotonic() >= {__import__('time').monotonic() + 0.4}", timeout=3)
        qa.eval("w=drv.main_window()\nwith bpy.context.temp_override(window=w):\n"
                f" result=w.mixar_qa_capture_frame(filepath={str(OUT / '02-voice-instructions.png')!r})")
        snap(qa, '03-listening-pill', {'surface':'pill_draft_preview'})
        qa.step('release_option_alt_finishes_voice', talk_key, qa, vp, 'RELEASE')
        qa.wait("bpy.context.window_manager.mixie_chat_voice_status=='Finishing'", timeout=10)
        qa.eval("import voice_focus_probe; voice_focus_probe.finish('Keep the camera.')")
        text = 'Vivid bevels. Keep the camera.'
        qa.wait(f'bpy.context.scene.mixie_chat_input=={text!r}', timeout=10)
        assert qa.eval("result=len(__import__('chat_send_probe').calls)") == 2
        assert qa.find(surface='pill_draft_preview')['widgets']
        qa.step('hold_again', talk_key, qa, vp, 'PRESS')
        qa.wait("bpy.context.window_manager.mixie_chat_voice_status=='Listening'", timeout=10)
        talk_key(qa, vp, 'RELEASE')
        qa.wait("bpy.context.window_manager.mixie_chat_voice_status=='Finishing'", timeout=10)
        qa.step('one_enter_sends_after_voice', qa.cmd, 'press', key='RET', window=vp['window'])
        qa.eval("import voice_focus_probe; voice_focus_probe.finish('Make it blue.')")
        results.append(assert_sent(qa, text+' Make it blue.', 3))
        restore(qa, after_send=True)
        snap(qa, '04-sent-once', {'prop':'mixie_chat_input'})
        assert qa.eval("result=len(__import__('chat_send_probe').calls)") == 3
        return {'passed':True, 'hover_enter_sends_once':True, 'hover_numpad_sends_once':True,
                'hover_shift_enter_newline':True, 'literal_v_preserved':True,
                'hold_option_alt_talk':True, 'tap_ignored':True, 'voice_enter_sends_once':True,
                'voice':'capture and transport fixtures', 'paid_requests':0, 'sends':results}
    finally:
        qa.eval('''
import chat_send_probe, voice_focus_probe
voice_focus_probe.uninstall()
bpy.context.window_manager.mixar_mark_armed=False
chat_send_probe.uninstall()
''')


if __name__ == '__main__':
    result=run(QA())
    (OUT/'verdict.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
