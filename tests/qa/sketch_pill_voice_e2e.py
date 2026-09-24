# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Voice reads Stop with a live ECG; the Sketch pill grows, blinks a caret and talks.

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4791 python3 tests/qa/sketch_pill_voice_e2e.py
Fresh isolated Dev app on macOS or Windows (the pill window exists only there).
Capture and dictation transport are local fixtures (a synthetic loud PCM chunk,
voice_focus_probe's transport); outgoing chat is chat_send_probe. Native clicks,
the pill gesture, the Sketch modal and the painted QA targets stay real.
No microphone, no paid requests. Review the screenshots alongside the verdict.
"""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from scribble_send_scenario import draw, viewport

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get('SKETCH_PILL_VOICE_QA_OUT', '/tmp/mixar-sketch-pill-voice'))


def snap(qa, name, target, margin=1000):
    qa.eval(f"w=drv.find_one(**{target!r})['_win']\n"
            "with bpy.context.temp_override(window=w):\n"
            "    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)")
    qa.cmd('snap', path=str(OUT / f'{name}.png'), target=target, margin=margin)


def status(qa, expected):
    qa.wait(f"bpy.context.window_manager.mixie_chat_voice_status=={expected!r}", timeout=10)


def pill_height(qa, surface):
    qa.wait(f"bool(drv.find(surface={surface!r}))", timeout=10)
    return qa.eval(f"w=drv.find_one(surface={surface!r})['_win']; result=w.height")


def caret_phases(qa, seconds=1.8, step=0.09):
    """Sample the painted caret; a blinking caret shows both phases."""
    seen = set()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qa.eval("w=drv.find_one(surface='pill_draft_preview')['_win']\n"
                "with bpy.context.temp_override(window=w):\n"
                "    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)")
        seen.add(qa.find(surface='pill_draft_preview')['widgets'][0].get('detail', ''))
        time.sleep(step)
    return seen


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval('''
import os, sys, struct
assert os.environ.get('MIXAR_QA') == '1'
assert not bpy.context.scene.mixie_chat_messages, 'Use a fresh QA scene'
sys.path.insert(0, QA_PATH)
import aud, chat_send_probe, voice_focus_probe
chat_send_probe.install()
voice_focus_probe.install()
# A loud 50 ms chunk per poll: the level (and so the ECG height) must rise.
_loud = struct.pack('<800h', *([12000, -12000] * 400))
aud._mixar_capture_read = lambda _: _loud
'''.replace('QA_PATH', repr(str(ROOT / 'tests/qa'))))
    try:
        # --- Expanded chat: Voice reads Stop with a stop square and live trace.
        qa.eval('bpy.ops.mixar.bubble_restore()')
        qa.wait("bool(drv.find(op='MIXIE_CHAT_OT_voice_toggle'))", timeout=10)
        snap(qa, '01-voice-idle', {'op': 'MIXIE_CHAT_OT_voice_toggle'}, margin=2500)
        qa.step('click_voice_in_island', qa.click, op='MIXIE_CHAT_OT_voice_toggle')
        status(qa, 'Listening')
        qa.wait('bpy.context.window_manager.mixie_chat_voice_level > 0.3', timeout=5)
        snap(qa, '02-voice-stop-and-ecg', {'op': 'MIXIE_CHAT_OT_voice_toggle'}, margin=2500)
        qa.step('stop_voice_in_island', qa.click, op='MIXIE_CHAT_OT_voice_toggle')
        status(qa, 'Finishing')
        assert qa.eval('result=bpy.context.window_manager.mixie_chat_voice_level') == 0.0
        qa.eval("import voice_focus_probe; voice_focus_probe.finish('Make it blue.')")
        qa.wait("bpy.context.scene.mixie_chat_input=='Make it blue.'", timeout=10)
        status(qa, '')

        # --- Resting pill height without Sketch, for the size comparison.
        qa.eval('bpy.ops.mixar.bubble_minimise()')
        rest_h = pill_height(qa, 'pill_cat')
        qa.eval('bpy.ops.mixar.bubble_restore()')
        qa.wait("bool(drv.find(op='MIXAR_OT_scribble_toggle'))", timeout=10)

        # --- Sketch: the pill grows, shows the draft with a caret and a Voice button.
        qa.step('sketch_minimizes', qa.click, op='MIXAR_OT_scribble_toggle')
        qa.wait("bool(drv.find(surface='pill_voice')) and bpy.context.window_manager.mixar_mark_armed",
                timeout=10)
        qa.wait(f"drv.find_one(surface='pill_draft_preview')['_win'].height > {rest_h}", timeout=5)
        sketch_h = pill_height(qa, 'pill_draft_preview')
        grow = sketch_h / rest_h
        assert 1.1 < grow < 1.25, (rest_h, sketch_h)
        assert qa.find(surface='pill_voice')['widgets'][0]['value'] == 'idle'
        phases = caret_phases(qa)
        assert phases == {'caret', ''}, f'caret must blink: {phases}'
        snap(qa, '03-sketch-pill-caret-and-voice', {'surface': 'pill_draft_preview'}, margin=100)

        vp = viewport(qa)
        qa.step('draw', draw, qa, vp, (.3, .58), (.44, .72))
        qa.cmd('type', text=' Keep the bevel.', window=vp['window'])
        preview = qa.find(surface='pill_draft_preview')['widgets'][0]
        assert preview['value'].endswith('Keep the bevel.'), preview
        assert preview.get('detail') == 'caret', 'typing keeps the caret solid'

        # --- The pill's Voice button: dictation without leaving Sketch or opening chat.
        qa.step('click_pill_voice', qa.click, surface='pill_voice')
        status(qa, 'Listening')
        qa.wait("drv.find_one(surface='pill_voice')['value']=='capturing'", timeout=5)
        assert qa.eval('result=bpy.context.window_manager.mixar_mark_armed')
        # The elongated pill paints this target only while it rests minimised
        # (hidden island uiBlocks stay in the dump, so they prove nothing).
        assert qa.find(surface='pill_draft_preview')['widgets'], 'the island stays minimised'
        snap(qa, '04-sketch-pill-listening-ecg', {'surface': 'pill_draft_preview'}, margin=100)
        # The keyboard went back to the viewport: typing still reaches the draft.
        qa.cmd('type', text='!', window=vp['window'])
        qa.wait("bpy.context.scene.mixie_chat_input.endswith('!')", timeout=5)
        qa.step('stop_pill_voice', qa.click, surface='pill_voice')
        status(qa, 'Finishing')
        qa.eval("import voice_focus_probe; voice_focus_probe.finish('Round it.')")
        status(qa, '')
        # The coordinator appends the words to the live draft.
        qa.wait("bpy.context.scene.mixie_chat_input=='Make it blue. Keep the bevel.! Round it.'",
                timeout=10)
        assert qa.eval('result=bpy.context.window_manager.mixar_mark_armed')
        assert qa.find(surface='pill_voice')['widgets'][0]['value'] == 'idle'

        # --- A click beside the button still opens the chat.
        qa.step('pill_text_click_restores', qa.click, surface='pill_draft_preview')
        qa.wait("bool(drv.find(op='MIXAR_OT_scribble_toggle'))", timeout=10)

        qa.step('send', qa.click, op='MIXIE_CHAT_OT_send_message')
        qa.wait("len(__import__('chat_send_probe').calls)==1", timeout=10)
        sent = qa.eval('''
import chat_send_probe
p=chat_send_probe.calls[-1]
result={'text':p['message'], 'images':len(p.get('image_attachments') or [])}
chat_send_probe.settle(bpy.context.scene)
''')
        return {'passed': True, 'island_voice_stop_ecg': True, 'level_rises': True,
                'sketch_pill_growth': round(grow, 3), 'caret_blinks': True,
                'typing_keeps_caret_solid': True, 'pill_voice_keeps_sketch': True,
                'keyboard_returns_to_viewport': True, 'pill_click_still_restores': True,
                'send': sent, 'voice': 'capture and transport fixtures', 'paid_requests': 0}
    finally:
        qa.eval('''
import chat_send_probe, voice_focus_probe
bpy.context.window_manager.mixar_mark_armed=False
voice_focus_probe.uninstall()
chat_send_probe.uninstall()
''')


if __name__ == '__main__':
    verdict = run(QA())
    (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))
