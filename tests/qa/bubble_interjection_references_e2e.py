#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-network replay: Send during an open run, with and without references.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT against an isolated
Dev app with outgoing connections blocked. Inspect the saved native frames.
"""
import os
from pathlib import Path
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from mixie_open_type_send_e2e import (
    FIELD, SCENE, SEND, assert_sent, draft_is, open_pill, press, type_draft, warp,
)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/bubble-interjection'))
    out.mkdir(parents=True, exist_ok=True)
    reference = out / 'reference.png'
    Image.new('RGB', (320, 240), (48, 130, 210)).save(reference)
    local = str(Path(__file__).resolve().parent)
    qa.eval(f'import sys; sys.path.insert(0, {local!r}); '
            'import chat_send_probe as p; p.install(); result=True')
    try:
        if qa.find(**FIELD)['total']:
            press(qa, 'ESC')
        qa.eval(f'scene={SCENE}; scene.mixie_chat_messages.clear(); '
                "scene.mixie_chat_pending_attachments.clear(); scene.mixie_chat_input=''; "
                "bpy.context.window_manager.mixar_bubble_tab='AGENT'; result=True")
        open_pill(qa)
        type_draft(qa, 'Start a local fixture run')
        warp(qa, SEND)
        qa.click(**SEND)
        assert_sent(qa, 'Start a local fixture run', 1)
        qa.eval(f'import chat_send_probe as p; p.chat_ops.get_session_manager().set_run({SCENE}, "qa-open-run", True); '
                'result=True')

        for index, with_reference in enumerate((False, True), start=2):
            if with_reference:
                qa.eval(f'result=list(bpy.ops.mixie_chat.add_image_from_file(filepath={str(reference)!r}))')
                qa.wait("bool(drv.find(surface='reference_column'))", timeout=5)
            qa.step(f"reopen_running_composer_{index}", open_pill, qa)
            assert qa.eval(f'result={SCENE}.mixie_run_open'), "Reopening the composer closed the run"
            text = f'Follow-up {index} while still running'
            type_draft(qa, text)
            draft_is(qa, text)
            qa.wait("len(drv.find(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_send_message'))==1",
                    timeout=5)
            send = qa.find(**SEND)['widgets']
            assert send[0]['region_type'] == ('UI' if with_reference else 'TOOLS'), send
            assert not qa.find(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_abort_session')['total']
            time.sleep(.35)
            qa.eval(f"hit=drv.find_one(**{FIELD!r}); win=hit['_win']\n"
                    "with bpy.context.temp_override(window=win):\n"
                    f"    result=win.mixar_qa_capture_frame(filepath={str(out / f'send-{index}.png')!r})")
            warp(qa, SEND)
            qa.click(**SEND)
            assert_sent(qa, text, index)
            qa.wait("bool(drv.find(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_abort_session'))",
                    timeout=5)
            assert qa.eval(f'result={SCENE}.mixie_run_open'), 'Follow-up closed the run'
            if with_reference:
                payload = qa.eval('import chat_send_probe as p; result=p.calls[-1]')
                assert payload['image_attachments'], payload
            qa.step(f'interjection_reference_{with_reference}', lambda: True)
        return {'dispatches': 3, 'backend_calls': 0, 'run_stayed_open': True}
    finally:
        qa.eval(f'import chat_send_probe as p; p.chat_ops.get_session_manager().set_run({SCENE}, "", False); '
                'p.uninstall(); result=True')


if __name__ == '__main__':
    run_scenario('bubble_interjection_references_e2e', run)
