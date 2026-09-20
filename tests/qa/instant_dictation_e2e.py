#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Immediate capture, Stop before Ready, and warmed startup through UAT1/Unmute.

QA_HARNESS, QA_PORT, DICTATION_QA_WAV (16 kHz mono PCM16) and QA_SCENARIO_OUT.
Uses paced sample audio at the capture boundary; spends transcription seconds
only, never sends an agent message. Native microphone capture is a separate test.
"""
import inspect
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from cloud_dictation_e2e import install_capture, type_draft

FIELD = {'prop': 'mixie_chat_input', 'area_type': 'AGENT_BUBBLE'}
VOICE = {'op': 'MIXIE_CHAT_OT_voice_toggle', 'area_type': 'AGENT_BUBBLE'}
IMPORTS = ('from mixar.modules.space_mixie_chat.core import voice\n'
           'from mixar.modules.space_mixie_chat.core.voice_input import warmup, transport\n')

def evaluate(qa, code):
    return qa.eval(IMPORTS + code)

def wait(qa, expression, **kwargs):
    for name, module in [('voice', 'mixar.modules.space_mixie_chat.core.voice'),
                         ('warmup', 'mixar.modules.space_mixie_chat.core.voice_input.warmup')]:
        expression = expression.replace(name + '.', f"__import__({module!r}, fromlist=['']).")
    return qa.wait(expression, **kwargs)


def main():
    qa = QA(port=int(os.environ.get('QA_PORT', '4784')))
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/instant-dictation-qa'))
    out.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'provider': 'UAT1/Unmute', 'capture': 'paced PCM fixture', 'cases': {}}
    try:
        qa.cmd('wait_login', timeout=60)
        qa.open_chat()
        evaluate(qa, 'from mixar.modules.space_mixie_chat.core import voice\n'
                'from mixar.modules.space_mixie_chat.core.voice_input import warmup, transport\n'
                'assert voice._session is None\n'
                "import aud; assert hasattr(aud, '_mixar_capture_permission_status')\n"
                "bpy.app.driver_namespace['_instant_connect'] = transport.Transport._connect\n"
                'result=True')
        duration = evaluate(qa, inspect.getsource(install_capture) + '\nresult=install_capture(' + repr(os.environ['DICTATION_QA_WAV']) + ')')
        for case in ('delayed_connection', 'prepared_connection'):
            type_draft(qa, 'Please:')
            if case == 'delayed_connection':
                evaluate(qa, 'warmup.shutdown()\n'
                        'def slow_connect(self, original=transport.Transport._connect):\n'
                        '    import time; time.sleep(8)\n'
                        '    return original(self)\n'
                        'transport.Transport._connect=slow_connect\nresult=True')
            else:
                evaluate(qa, "transport.Transport._connect=bpy.app.driver_namespace['_instant_connect']\n"
                        'from mixar.config.config import get_server_url\n'
                        'from mixar.modules.auth.core.auth import get_access_token\n'
                        'warmup.prepare(get_server_url(), get_access_token())\nresult=True')
                wait(qa, 'warmup._candidate is not None and warmup._candidate.socket is not None', timeout=20)
            began = time.monotonic()
            qa.click(**VOICE)
            wait(qa, "bpy.context.window_manager.mixie_chat_voice_status == 'Listening'", timeout=2)
            startup = evaluate(qa, 'result={"ready":voice._session.ready, "capturing":voice._session.capture is not None, '
                              '"capture_ms":voice._session.transport.timings["click_to_capture_ms"]}')
            assert startup['capturing'] and startup['capture_ms'] < 250, startup
            if case == 'delayed_connection':
                assert not startup['ready'], startup
            qa.cmd('snap', path=str(out / (case + '-listening.png')), target=VOICE, margin=1500)
            wait(qa, f'__import__("time").monotonic()-voice._session.recording_at >= {duration + .05}', timeout=10)
            if case == 'delayed_connection':
                assert evaluate(qa, 'result=voice._session.ready') is False
            qa.click(**VOICE)
            if case == 'delayed_connection':
                assert evaluate(qa, 'result=voice._session.capture is None and voice._session.state=="Finishing"')
            wait(qa, 'not bpy.context.window_manager.mixie_chat_voice_listening', timeout=35)
            value = evaluate(qa, 'result={"text":drv.main_window().scene.mixie_chat_input, "timings":voice._last_timings, '
                            '"sent":sum(m.sender=="USER" for m in drv.main_window().scene.mixie_chat_messages)}')
            text = value['text'].lower()
            assert text.startswith('please:') and 'cube' in text and 'bevel' in text and '0.02' in text and 'camera' in text and 'not delete' in text, value
            assert value['sent'] == 0, value
            assert value['timings']['warm_connection'] == (case == 'prepared_connection'), value
            assert qa.find(**FIELD)['widgets'][0].get('text_edit'), 'composer focus missing'
            report['cases'][case] = {'startup': startup, **value, 'elapsed_s': round(time.monotonic()-began, 2)}
            qa.cmd('snap', path=str(out / (case + '-final.png')), target=FIELD, margin=1500)
        report['passed'] = True
    finally:
        evaluate(qa, "from mixar.modules.space_mixie_chat.core import voice; voice.cancel()\n"
                'from mixar.modules.space_mixie_chat.core.voice_input import transport\n'
                "saved=bpy.app.driver_namespace.pop('_instant_connect', None)\n"
                'if saved: transport.Transport._connect=saved\n'
                "import aud\nfor k,v in bpy.app.driver_namespace.pop('_dictation_capture_saved', {}).items(): setattr(aud,k,v)\nresult=True")
        (out / 'verdict.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
