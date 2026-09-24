#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real field dictation: active status persists, empty-result notice expires.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT against an isolated
event-simulation Dev app. Only audio/provider boundaries are fixtures; no credits.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from mixie_open_type_send_e2e import open_pill
from voice_fields_e2e import CHAT, hold, release, finish, require, set_text

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/voice-toast-expiry'))
STORE = "__import__('mixar.modules.common.notifications', fromlist=['get_notification_store']).get_notification_store()"


def snapshot(qa, name):
    qa.eval("bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2); result=True")
    qa.cmd('snap', path=str(OUT / f'{name}.png'))


def active_status(qa):
    set_text(qa, CHAT, 'Keep this draft')
    hold(qa, CHAT)
    time.sleep(5.5)
    require(qa.eval(f"result={STORE}.contains('voice_input:field-status')"),
            'Listening status expired while capture was active')
    snapshot(qa, 'listening-persists')


def empty_result(qa):
    release(qa, CHAT)
    finish(qa, '')
    require(qa.eval(f"result={STORE}.contains('voice_input')"), 'Empty-result notice missing')
    require(not qa.eval(f"result={STORE}.contains('voice_input:field-status')"),
            'Recording status survived completion')
    require(qa.eval("result=drv.main_window().scene.mixie_chat_input == 'Keep this draft'"),
            'Empty dictation changed the draft')
    snapshot(qa, 'empty-result-visible')
    qa.wait(f"not {STORE}.contains('voice_input')", timeout=7)
    time.sleep(.5)
    snapshot(qa, 'empty-result-expired')


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    local = str(Path(__file__).resolve().parent)
    qa.eval(f'import sys; sys.path.insert(0, {local!r}); import voice_focus_probe as v; '
            'v.install(); bpy.context.window_manager.mixie_chat_is_logged_in=True; result=True')
    try:
        open_pill(qa)
        qa.step('active_status_survives_five_seconds', active_status, qa)
        qa.step('empty_transcript_notice_expires', empty_result, qa)
        return {'snapshots': str(OUT), 'backend_calls': 0}
    finally:
        qa.eval('import voice_focus_probe as v; v.uninstall(); result=True')


if __name__ == '__main__':
    run_scenario('voice_toast_expiry_e2e', run)
