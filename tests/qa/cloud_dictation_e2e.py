#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real app → UAT1 → Unmute, with deterministic PCM at the capture boundary.

Needs QA_HARNESS, DICTATION_QA_WAV (16 kHz mono PCM16), and QA_PORT (4783).
This proves live transport/composer UI, not physical microphone capture.
Leaves screenshots and verdict. Audio contains only the supplied test phrase.
"""
import inspect
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA


def type_draft(qa, text):
    qa.cmd('set_text', widget={'prop': 'mixie_chat_input'}, text=text, enter=False)
    # Harness type_char leaves shift=True after a final shifted character
    # (e.g. ':'). Release it explicitly or Voice receives Shift-click/Cancel.
    qa.eval("drv.press(drv.find_one(prop='mixie_chat_input')['_win'], 'LEFT_SHIFT')")


def install_capture(path):
    import aud
    import time
    import wave
    import bpy
    import qa_driver as drv
    from mixar.modules.space_mixie_chat.core import voice
    from mixar.config.config import get_server_url
    assert get_server_url() == 'https://uat1.mixar.app'
    voice.cancel()
    with wave.open(path, 'rb') as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        pcm = wav.readframes(wav.getnframes())
    saved = {name: getattr(aud, name) for name in (
        '_mixar_capture_permission', '_mixar_capture_open', '_mixar_capture_read', '_mixar_capture_stop')}
    def opened():
        return {'began': time.monotonic(), 'cursor': 0}
    def read(handle):
        end = min(len(pcm), int((time.monotonic() - handle['began']) * 16000) * 2)
        data = pcm[handle['cursor']:end]
        handle['cursor'] = end
        return data
    aud._mixar_capture_permission = lambda: 1
    aud._mixar_capture_open = opened
    aud._mixar_capture_read = read
    aud._mixar_capture_stop = read
    bpy.app.driver_namespace['_dictation_capture_saved'] = saved
    return len(pcm) / 32000


def main():
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixie-dictation-qa'))
    out.mkdir(parents=True, exist_ok=True)
    qa = QA(port=int(os.environ.get('QA_PORT', '4783')))
    result = {'capture': 'paced PCM fixture', 'backend': 'uat1', 'passed': False}
    try:
        qa.cmd('reset_state')
        qa.cmd('wait_login', timeout=60)
        qa.wait("drv.main_window().scene.mixie_chat_state == 'IDLE'", timeout=30)
        qa.open_chat()
        duration = qa.eval(inspect.getsource(install_capture) + '\nresult = install_capture(' + repr(os.environ['DICTATION_QA_WAV']) + ')')
        type_draft(qa, 'Please:')
        qa.click(op='MIXIE_CHAT_OT_voice_toggle')
        qa.wait("bpy.context.window_manager.mixie_chat_voice_status == 'Listening'", timeout=20)
        qa.cmd('snap', path=str(out/'listening.png'), target={'op': 'MIXIE_CHAT_OT_voice_toggle'}, margin=1000)
        time.sleep(float(duration) + .2)
        qa.click(op='MIXIE_CHAT_OT_voice_toggle')
        qa.wait("not bpy.context.window_manager.mixie_chat_voice_listening", timeout=40)
        text = qa.eval('result = drv.main_window().scene.mixie_chat_input')
        assert text.startswith('Please:') and 'camera' in text.lower(), text
        assert '0.02' in text and 'not delete' in text.lower(), text
        result['transcript'] = text
        qa.cmd('snap', path=str(out/'transcript.png'), target={'op': 'MIXIE_CHAT_OT_voice_toggle'}, margin=1000)
        # No automatic agent submission occurred.
        state = qa.eval('result = drv.main_window().scene.mixie_chat_state')
        assert state == 'IDLE', state
        # Cancel after actual provider readiness; final cannot replace draft.
        type_draft(qa, 'Keep my draft')
        qa.click(op='MIXIE_CHAT_OT_voice_toggle')
        qa.wait("bpy.context.window_manager.mixie_chat_voice_status == 'Listening'", timeout=20)
        qa.eval('from mixar.modules.space_mixie_chat.core import voice; voice.cancel()')
        time.sleep(1)
        assert qa.eval('result = drv.main_window().scene.mixie_chat_input') == 'Keep my draft'
        result['passed'] = True
    finally:
        qa.eval("from mixar.modules.space_mixie_chat.core import voice; voice.cancel(); import aud\nfor k,v in bpy.app.driver_namespace.pop('_dictation_capture_saved', {}).items(): setattr(aud,k,v)")
        (out/'verdict.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
