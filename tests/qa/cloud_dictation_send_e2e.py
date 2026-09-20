#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit Send during real cloud dictation, followed by a real agent reply.

Uses a benign greeting WAV via DICTATION_QA_WAV. Spends one small agent turn
plus a few seconds of Unmute audio; default QA port 4783. Capture is a fixture.
"""
import inspect
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from cloud_dictation_e2e import install_capture


def main():
    qa = QA(port=int(os.environ.get('QA_PORT', '4783')))
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixie-dictation-send-qa'))
    out.mkdir(parents=True, exist_ok=True)
    verdict = {'capture': 'paced PCM fixture', 'passed': False}
    try:
        qa.cmd('reset_state')
        qa.cmd('wait_login', timeout=60)
        qa.wait("drv.main_window().scene.mixie_chat_state == 'IDLE'", timeout=30)
        qa.open_chat()
        before = qa.eval("result = sum(m.sender == 'USER' for m in drv.main_window().scene.mixie_chat_messages)")
        duration = qa.eval(inspect.getsource(install_capture) + '\nresult = install_capture(' + repr(os.environ['DICTATION_QA_WAV']) + ')')
        qa.eval("drv.main_window().scene.mixie_chat_input = ''")
        qa.click(op='MIXIE_CHAT_OT_voice_toggle')
        qa.wait("bpy.context.window_manager.mixie_chat_voice_status == 'Listening'", timeout=20)
        time.sleep(float(duration) + .2)
        qa.click(op='MIXIE_CHAT_OT_send_message')
        qa.cmd('snap', path=str(out/'finishing.png'), target={'op': 'MIXIE_CHAT_OT_voice_toggle'}, margin=1000)
        qa.wait(f"sum(m.sender == 'USER' for m in drv.main_window().scene.mixie_chat_messages) > {before}", timeout=40)
        qa.wait_turn(timeout=180)
        after = qa.eval("result = sum(m.sender == 'USER' for m in drv.main_window().scene.mixie_chat_messages)")
        assert after == before + 1, (before, after)
        assert qa.eval('result = drv.main_window().scene.mixie_chat_input') == ''
        qa.open_chat()
        qa.cmd('snap', path=str(out/'reply.png'), target={'op': 'MIXIE_CHAT_OT_voice_toggle'}, margin=1000)
        verdict.update(passed=True, new_user_messages=after-before)
    finally:
        qa.eval("from mixar.modules.space_mixie_chat.core import voice; voice.cancel(); import aud\nfor k,v in bpy.app.driver_namespace.pop('_dictation_capture_saved', {}).items(): setattr(aud,k,v)")
        (out/'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))


if __name__ == '__main__':
    main()
