#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline macOS regression: focused composer -> checkpoint -> close -> restore.

Launch an isolated QA profile with external networking blocked. Set QA_HARNESS,
MIXAR_QA_PORT and QA_SCENARIO_OUT. Twelve real fresh-turn saves alternate Enter
and Send. Only auth/transport are fixtures; checkpoints, Cocoa windows and UI
events are real. The newest checkpoint is restored through the native card.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from mixie_open_type_send_e2e import (
    FIELD, SEND, SCENE, assert_sent, draft_is, open_pill, press, settle,
    type_draft, warp,
)


def capture(qa, out, name):
    qa.eval('import qa_region_capture as cap\n'
            f'w=drv.find_one(**{FIELD!r})["_win"]\n'
            f'cap.start({str(out / (name + ".png"))!r}, w.as_pointer())\nresult=True')
    qa.wait('__import__("qa_region_capture").done', timeout=6)
    assert qa.eval('import qa_region_capture as cap; result=cap.error') is None


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/bubble-checkpoint-crash'))
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.types.Scene, 'mixie_chat_input')", timeout=30)
    qa.eval(f'import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); result=True')
    qa.eval(f'''
import os
from pathlib import Path
from mixar.modules.space_mixie_chat.core import checkpoint_store as store, turn_checkpoints as cp
import chat_send_probe as probe
assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA app'
drv._crash_old_root = store.checkpoints_root
drv._crash_old_cp_root = cp.checkpoints_root
store.checkpoints_root = lambda: {str(out / 'checkpoints')!r}
cp.checkpoints_root = store.checkpoints_root
probe.install()
scene = {SCENE}
scene.mixie_chat_messages.clear()
scene.mixie_chat_input = ''
scene.mixie_session_id = ''
scene.mixie_chat_mode = 'AGENT'
scene['qa_checkpoint_marker'] = 'before'
bpy.context.window_manager.mixar_bubble_tab = 'AGENT'
result = True
''')
    try:
        qa.dismiss_splash()
        records = []
        for index in range(12):
            qa.step(f'open_{index}', open_pill, qa)
            message = f'Checkpoint close regression {index + 1}'
            qa.step(f'type_{index}', type_draft, qa, message)
            draft_is(qa, message)
            if index == 0:
                capture(qa, out, 'focused-before-send')
            if index % 2:
                warp(qa, SEND)
                qa.step(f'click_send_{index}', qa.click, **SEND)
            else:
                qa.step(f'enter_send_{index}', press, qa, 'RET')
            qa.step(f'dispatch_once_{index}', assert_sent, qa, message, index + 1)
            records = qa.eval(f'''
from mixar.modules.space_mixie_chat.core import turn_checkpoints as cp
result = cp.list_checkpoints({SCENE}.mixie_session_id)
''')
            turns = [r for r in records if r['kind'] == 'turn']
            assert len(turns) == index + 1, records
            assert all(r['bytes'] > 0 for r in turns), turns
            qa.wait("bool(drv.find(surface='pill_cat'))", timeout=8)
            settle(qa)
        open_pill(qa)
        capture(qa, out, 'after-twelve-saves')
        qa.eval(f"{SCENE}['qa_checkpoint_marker']='after'; result=True")
        target = {'op': 'MIXIE_CHAT_OT_show_checkpoints', 'area_type': 'AGENT_BUBBLE'}
        warp(qa, target)
        qa.click(**target)
        qa.wait("bool(drv.find(surface='chat_checkpoint_row'))", timeout=5)
        # The first visible (newest) turn is enough to prove the UI file-read
        # path. Its scene marker predates the edit above.
        row = qa.find(surface='chat_checkpoint_row')['widgets'][0]
        query = {'surface': 'chat_checkpoint_row', 'index': row['index']}
        warp(qa, query)
        qa.click(**query)
        time.sleep(.25)
        qa.click(**query)
        qa.wait(f"{SCENE}.get('qa_checkpoint_marker') == 'before'", timeout=20)
        qa.wait("bool(drv.find(surface='pill_cat'))", timeout=10)
        settle(qa)
        open_pill(qa)
        saved_draft = qa.eval(f'result={SCENE}.mixie_chat_input')
        type_draft(qa, 'Typing works after checkpoint restore')
        draft_is(qa, saved_draft + 'Typing works after checkpoint restore')
        capture(qa, out, 'restored-and-editable')
        return {'fresh_turn_saves': 12, 'enter': 6, 'send_click': 6,
                'checkpoint_ui_restore': True, 'backend_calls': 0,
                'evidence': str(out)}
    finally:
        qa.eval('import chat_send_probe as p; p.uninstall(); '
                'from mixar.modules.space_mixie_chat.core import checkpoint_store as s, turn_checkpoints as cp; '
                's.checkpoints_root=drv._crash_old_root; '
                'cp.checkpoints_root=drv._crash_old_cp_root; result=True')


if __name__ == '__main__':
    run_scenario('bubble_checkpoint_crash_e2e', run)
