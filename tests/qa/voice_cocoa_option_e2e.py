#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native Cocoa right Option stays typing; left Option dictates at the caret.

Launch launch_dictation_qa.py with QA_RECORD=1, QA_BACKEND_URL=http://127.0.0.1:9.
Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT to replay. Only audio and
transcription are fixtures. No microphone or external service is used.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario, ScenarioFail

FIELD = {'area_type': 'AGENT_BUBBLE', 'prop': 'mixie_chat_input'}


def require(value, message):
    if not value:
        raise ScenarioFail(message)


def option(qa, pressed, right=False):
    qa.eval(f'import cocoa_option_probe as c; c.option({FIELD!r}, {pressed!r}, '
            f'right={right!r}); result=True')


def snap(qa, out, name):
    qa.eval("bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2); result=True")
    qa.cmd('snap', path=str(out / (name + '.png')), target=FIELD, margin=200)


def right_case(qa, out):
    option(qa, True, right=True)
    time.sleep(.65)
    require(not qa.eval('result=bpy.context.window_manager.mixie_chat_voice_listening'),
            'Right Option started voice')
    require(qa.eval('import voice_focus_probe as v; result=v.latest is None'),
            'Right Option briefly opened capture')
    snap(qa, out, 'right-option-no-capture')
    option(qa, False, right=True)
    require(qa.find(**FIELD)['widgets'][0].get('text_edit'), 'Right Option left text editing')


def left_case(qa, out):
    option(qa, True)
    # AppKit may reconcile a synthetic hold with the actually unpressed
    # hardware key before the next QA poll. Require capture really opened;
    # a brief Listening state followed by Finishing is valid for this probe.
    qa.wait("__import__('voice_focus_probe').latest is not None and "
            "'capture_open_ms' in __import__('voice_focus_probe').latest.timings", timeout=5)
    require(qa.eval('from mixar.modules.space_mixie_chat.core import voice; '
                    'result=bool(voice._session.field_token)'), 'No native field ownership')
    snap(qa, out, 'left-option-capture')
    option(qa, False)
    qa.wait("bpy.context.window_manager.mixie_chat_voice_status == 'Finishing'", timeout=5)
    qa.eval("import voice_focus_probe as v; v.finish('Left Option works'); result=True")
    qa.wait("drv.main_window().scene.mixie_chat_input == 'Left Option works'", timeout=5)
    edit = qa.find(**FIELD)['widgets'][0].get('text_edit')
    require(edit and edit['cursor'] == 17, f'Wrong final caret: {edit}')
    snap(qa, out, 'left-option-transcript')


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT'])
    out.mkdir(parents=True, exist_ok=True)
    local = str(Path(__file__).resolve().parent)
    qa.eval(f"import sys; sys.path.insert(0,{local!r}); "
            "import voice_focus_probe as v; import cocoa_option_probe as c; v.install(); v.latest=None; "
            "bpy.context.window_manager.mixie_chat_is_logged_in=True; "
            "drv.main_window().scene.mixie_chat_input=''; "
            "bpy.ops.mixar.agent_bubble_open_window(); result=True")
    try:
        qa.wait(f'bool(drv.find(**{FIELD!r}))', timeout=5)
        qa.eval(f'import cocoa_option_probe as c; c.activate({FIELD!r}); result=True')
        time.sleep(.3)  # Let native window-activation events settle before editing.
        qa.eval(f'import cocoa_option_probe as c; c.focus_composer({FIELD!r}); result=True')
        require(qa.find(**FIELD)['widgets'][0].get('text_edit'), 'No initial text editor')
        qa.step('native_right_option_does_not_capture', right_case, qa, out)
        qa.step('native_left_option_inserts_transcript', left_case, qa, out)
        return {'capture': 'fixture', 'events': 'AppKit event queue through GHOST',
                'snapshots': str(out)}
    finally:
        try:
            option(qa, False)
        finally:
            qa.eval('import voice_focus_probe as v; v.uninstall(); result=True')


if __name__ == '__main__':
    run_scenario('voice_cocoa_option_e2e', run)
