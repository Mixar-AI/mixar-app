#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Stop -> transcript -> edit/Enter without clicking the composer (no credits).

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4784 \
  QA_SCENARIO_OUT=/tmp/voice-focus python3 tests/qa/voice_composer_focus_e2e.py
Only capture/transcription and outgoing agent transport are local fixtures.
Real native controls, coordinator, text edit, Enter and Send are exercised.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario
from mixie_open_type_send_e2e import open_pill, assert_sent, settle

SCENE = 'drv.main_window().scene'
FIELD = {'area_type': 'AGENT_BUBBLE', 'prop': 'mixie_chat_input'}
VOICE = {'area_type': 'AGENT_BUBBLE', 'op': 'MIXIE_CHAT_OT_voice_toggle'}


def field(qa):
    return qa.find(**FIELD)['widgets'][0]


def focus_state(qa, text):
    qa.wait(f'{SCENE}.mixie_chat_input == {text!r}', timeout=5)
    widget = field(qa)
    edit = widget.get('text_edit')
    if not edit:
        raise ScenarioFail(f'transcript arrived without text editing: {widget}')
    if edit['cursor'] != len(text.encode('utf-8')) or edit['selection'][0] != edit['selection'][1]:
        raise ScenarioFail(f'caret is not at the end of the unselected transcript: {edit}')
    return edit


def dictation(qa, transcript):
    qa.click(**VOICE)
    qa.wait("bpy.context.window_manager.mixie_chat_voice_status == 'Listening'", timeout=5)
    qa.click(**VOICE)
    qa.wait("bpy.context.window_manager.mixie_chat_voice_status == 'Finishing'", timeout=5)
    qa.eval(f'import voice_focus_probe as v; v.finish({transcript!r}); result=True')
    qa.wait('not bpy.context.window_manager.mixie_chat_voice_listening', timeout=5)


def snap(qa, out, name):
    time.sleep(.35)
    qa.cmd('snap', path=str(out / f'{name}.png'), target=FIELD, margin=1500)


def run(qa):
    global FIELD, VOICE
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/voice-focus')) / 'snaps'
    out.mkdir(parents=True, exist_ok=True)
    local = str(Path(__file__).resolve().parent)
    open_pill(qa)
    qa.eval(f'import sys; sys.path.insert(0, {local!r}); '
            'import chat_send_probe as p; import voice_focus_probe as v; '
            'p.install(); v.install(); result=True')
    try:
        qa.eval('bpy.ops.mixie_chat.ink_release_composer(); '
                f'scene={SCENE}; scene.mixie_chat_messages.clear(); '
                "scene.mixie_chat_input=''; scene.mixie_chat_mode='AGENT'; result=True")
        open_pill(qa)
        qa.step('empty_chat_dictation', dictation, qa, 'Make a blue cube')
        qa.step('empty_chat_has_caret', focus_state, qa, 'Make a blue cube')
        qa.step('empty_chat_picture', snap, qa, out, 'empty-transcript')
        qa.press('RET', window=field(qa)['window'])
        qa.step('enter_sends_without_field_click', assert_sent, qa, 'Make a blue cube', 1)
        settle(qa)
        open_pill(qa)
        qa.step('conversation_dictation', dictation, qa, 'Add a bevel')
        qa.step('conversation_has_caret', focus_state, qa, 'Add a bevel')
        qa.cmd('type', window=field(qa)['window'], text=' please')
        qa.step('editing_preserves_transcript', focus_state, qa, 'Add a bevel please')
        qa.step('conversation_picture', snap, qa, out, 'conversation-transcript')
        qa.press('RET', window=field(qa)['window'])
        qa.step('edited_transcript_sent_once', assert_sent, qa, 'Add a bevel please', 2)
        settle(qa)
        open_pill(qa)
        # Typing while the final is pending must retain those edits and refresh
        # the native private buffer before the next character is entered.
        qa.click(**VOICE)
        qa.wait("bpy.context.window_manager.mixie_chat_voice_status == 'Listening'", timeout=5)
        qa.click(**VOICE)
        qa.cmd('set_text', widget=FIELD, text='Keep this', enter=False)
        qa.eval("import voice_focus_probe as v; v.finish('and the camera'); result=True")
        qa.wait('not bpy.context.window_manager.mixie_chat_voice_listening', timeout=5)
        qa.step('pending_edit_kept', focus_state, qa, 'Keep this and the camera')
        qa.cmd('type', window=field(qa)['window'], text=' too')
        qa.step('native_buffer_refreshed', focus_state, qa, 'Keep this and the camera too')
        qa.step('preserved_edits_picture', snap, qa, out, 'preserved-edits')
        qa.press('RET', window=field(qa)['window'])
        qa.step('combined_draft_sent_once', assert_sent, qa, 'Keep this and the camera too', 3)
        settle(qa)
        return {'sends': 3, 'backend_calls': 0, 'snapshots': str(out),
                'platform': qa.eval('import sys; result=sys.platform')}
    finally:
        qa.eval('import voice_focus_probe as v; import chat_send_probe as p; '
                'v.uninstall(); p.uninstall(); result=True')



if __name__ == '__main__':
    run_scenario('voice_composer_focus_e2e', run)
