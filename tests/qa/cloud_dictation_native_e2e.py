#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native mic → UAT1 → Unmute → draft, driven entirely through the QA harness.

macOS acoustic smoke: plays DICTATION_QA_WAV through the current speakers.
Requires microphone permission and audible speaker-to-microphone routing.
Records briefly using the real microphone; does not submit an agent message.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from cloud_dictation_e2e import type_draft


def main():
    qa = QA(port=int(os.environ.get('QA_PORT', '4783')))
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixie-dictation-native-qa'))
    out.mkdir(parents=True, exist_ok=True)
    verdict = {'capture': 'native microphone with speaker playback', 'passed': False}
    try:
        qa.cmd('reset_state')
        qa.cmd('wait_login', timeout=60)
        qa.wait("drv.main_window().scene.mixie_chat_state == 'IDLE'", timeout=30)
        qa.open_chat()
        qa.eval("import aud, inspect\n"
                "from mixar.config.config import get_server_url\n"
                "assert get_server_url() == 'https://uat1.mixar.app'\n"
                "assert inspect.isbuiltin(aud._mixar_capture_open)\n"
                "assert aud._mixar_capture_permission() == 1")
        # Native text editing owns an active buffer; direct RNA assignment can
        # be overwritten when clicking away. Type through the widget instead.
        # set_text commits with Enter, which submits a chat. Leave editing
        # active exactly as a person typing then clicking Voice would do.
        type_draft(qa, 'Please:')
        before = qa.eval("result = sum(m.sender == 'USER' for m in drv.main_window().scene.mixie_chat_messages)")
        qa.click(op='MIXIE_CHAT_OT_voice_toggle')
        qa.wait("bpy.context.window_manager.mixie_chat_voice_status == 'Listening'", timeout=20)
        assert qa.eval('result = drv.main_window().scene.mixie_chat_input') == 'Please:'
        qa.cmd('snap', path=str(out/'listening.png'), target={'op': 'MIXIE_CHAT_OT_voice_toggle'}, margin=1000)
        subprocess.run(['afplay', os.environ['DICTATION_QA_WAV']], check=True)
        qa.click(op='MIXIE_CHAT_OT_voice_toggle')
        qa.wait("not bpy.context.window_manager.mixie_chat_voice_listening", timeout=40)
        text = qa.eval('result = drv.main_window().scene.mixie_chat_input')
        verdict['transcript'] = text
        verdict['notifications'] = qa.eval("from mixar.modules.common.notifications import get_notification_store\nresult = [str(n) for n in get_notification_store().get_visible()]")
        qa.cmd('snap', path=str(out/'transcript.png'), target={'op': 'MIXIE_CHAT_OT_voice_toggle'}, margin=1000)
        assert text.startswith('Please:') and 'camera' in text.lower(), text
        assert '0.02' in text and 'not delete' in text.lower(), text
        after = qa.eval("result = sum(m.sender == 'USER' for m in drv.main_window().scene.mixie_chat_messages)")
        assert before == after, (before, after)
        verdict['passed'] = True
    finally:
        qa.eval('from mixar.modules.space_mixie_chat.core import voice; voice.cancel()')
        (out/'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))


if __name__ == '__main__':
    main()
