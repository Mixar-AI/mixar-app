#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real composer/worker with paced PCM and a delayed one-second-cap relay fixture.

QA_HARNESS, QA_PORT, DICTATION_QA_WAV and QA_SCENARIO_OUT; no cloud calls.
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
from instant_dictation_e2e import evaluate, wait, FIELD, VOICE


def install_relay():
    import json
    import time
    import bpy
    from mixar.modules.space_mixie_chat.core.voice_input import warmup, transport
    warmup.shutdown()
    saved = transport.Transport._connect
    sockets = []
    class Socket:
        def __init__(self):
            self.audio = bytearray()
            self.controls = []
            self.sid = None
            self.ready = False
            self.closed = False
        def settimeout(self, _):
            pass
        def send(self, raw):
            value = json.loads(raw)
            self.controls.append(value['type'])
            self.sid = value.get('dictation_id', self.sid)
        def send_binary(self, data):
            assert 'stop' not in self.controls
            self.audio.extend(data)
            assert len(self.audio) <= 32000, 'client exceeded advertised cap'
        def recv(self):
            if not self.ready:
                self.ready = True
                return json.dumps({'type': 'ready', 'max_duration_seconds': 1,
                                   'max_startup_buffer_seconds': 20})
            assert self.controls[-1] == 'stop'
            return json.dumps({'type': 'final', 'dictation_id': self.sid, 'text': 'Keep the light'})
        def close(self, **_):
            self.closed = True
    def connect(worker):
        time.sleep(2.5)
        socket = Socket()
        sockets.append(socket)
        return socket
    transport.Transport._connect = connect
    bpy.app.driver_namespace['_cap_qa'] = (saved, sockets)


def main():
    qa = QA(port=int(os.environ.get('QA_PORT', '4784')))
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/dictation-cap-qa'))
    out.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'capture': 'paced PCM fixture', 'relay': 'local cap fixture', 'cases': {}}
    try:
        qa.cmd('wait_login', timeout=60)
        qa.open_chat()
        qa.eval(inspect.getsource(install_capture) + '\nresult=install_capture(' + repr(os.environ['DICTATION_QA_WAV']) + ')')
        qa.eval(inspect.getsource(install_relay) + '\ninstall_relay(); result=True')
        for case in ('auto_limit', 'stop_before_ready'):
            type_draft(qa, 'Please:')
            qa.click(**VOICE)
            wait(qa, "voice._session is not None and voice._session.capture is not None", timeout=2)
            if case == 'stop_before_ready':
                time.sleep(1.3)
                assert evaluate(qa, 'result=not voice._session.ready')
                qa.click(**VOICE)
            wait(qa, 'voice._session is None', timeout=10)
            value = qa.eval("sockets=bpy.app.driver_namespace['_cap_qa'][1]\n"
                            "s=[s for s in sockets if 'start' in s.controls][-1]\n"
                            "result={'bytes':len(s.audio), 'controls':s.controls, 'closed':s.closed, "
                            "'text':drv.main_window().scene.mixie_chat_input}")
            assert value == {'bytes': 32000, 'controls': ['start', 'stop'], 'closed': True,
                             'text': 'Please: Keep the light'}, value
            assert qa.find(**FIELD)['widgets'][0].get('text_edit'), 'composer focus missing'
            qa.cmd('snap', path=str(out / (case + '.png')), target=FIELD, margin=1500)
            report['cases'][case] = value
        report['passed'] = True
    finally:
        evaluate(qa, "voice.cancel()\nsaved=bpy.app.driver_namespace.pop('_cap_qa', None)\n"
                 'if saved: transport.Transport._connect=saved[0]\n'
                 "import aud\nfor k,v in bpy.app.driver_namespace.pop('_dictation_capture_saved', {}).items(): setattr(aud,k,v)\nresult=True")
        (out / 'verdict.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
