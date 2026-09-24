#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""PR 1588 regressions: pending/active Escape and field-aware transcript text.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT in an isolated Dev app.
Real native input/editing; fixture microphone/provider boundaries; no credits.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from mixie_open_type_send_e2e import open_pill
from voice_fields_e2e import (CHAT, TEXT, SHORT, caret, finish, focus, hold, key,
                             release, require, set_text)

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/voice-review-fixes'))


def snapshot(qa, name, target):
    qa.eval("bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2); result=True")
    qa.cmd('snap', path=str(OUT / f'{name}.png'), target=target, margin=400)


def open_popup(qa):
    qa.eval("bpy.ops.qa.voice_fields('INVOKE_DEFAULT'); result=True")
    qa.wait(f'bool(drv.find(**{TEXT!r}))', timeout=5)


def escape_pending(qa):
    open_popup(qa)
    set_text(qa, TEXT, 'discard this edit')
    # Queue the chord together so transport latency cannot cross the 300 ms
    # hold threshold. These still enter the real window-manager event queue.
    qa.eval(f"""
w=drv.find_one(**{TEXT!r})['_win']
drv._sim(w,type='LEFT_ALT',value='PRESS',alt=True)
drv._sim(w,type='ESC',value='PRESS',alt=True)
drv._sim(w,type='ESC',value='RELEASE',alt=True)
drv._sim(w,type='LEFT_ALT',value='RELEASE',alt=False)
result=True
""")
    time.sleep(.15)
    require(not qa.find(**TEXT)['widgets'][0].get('text_edit'),
            'Esc before capture failed to leave native text editing')
    require(qa.eval("import voice_field_probe as f; result=f.active.text == 'popup seed'"),
            'Esc before capture failed to revert the original text')
    require(qa.eval('import voice_focus_probe as v; result=v.latest is None'),
            'Pre-start Esc opened capture')
    snapshot(qa, 'pending-escape-reverted', TEXT)


def escape_active(qa):
    set_text(qa, TEXT, 'keep this edit')
    hold(qa, TEXT)
    key(qa, TEXT, 'ESC')
    qa.wait('not bpy.context.window_manager.mixie_chat_voice_listening', timeout=5)
    require(qa.find(**TEXT)['widgets'][0].get('text_edit'),
            'Esc during capture cancelled the field edit')
    qa.eval(f"w=drv.find_one(**{TEXT!r})['_win']; "
            "drv._sim(w,type='LEFT_ALT',value='RELEASE',alt=False); result=True")
    snapshot(qa, 'active-escape-preserved', TEXT)
    focus(qa, SHORT)
    require(qa.eval("import voice_field_probe as f; result=f.active.text == 'keep this edit'"),
            'Esc during capture lost the edited text')


def single_line(qa):
    # The first click away from another popup editor only commits that editor.
    # Activate this field before set_text sends its select-all/type sequence.
    focus(qa, TEXT)
    set_text(qa, TEXT, 'replace me')
    key(qa, TEXT, 'A', oskey=True)
    hold(qa, TEXT)
    release(qa, TEXT)
    finish(qa, 'café\r\nblue\tcube\x07\x1f\x7f')
    caret(qa, TEXT, 'café blue cube')
    snapshot(qa, 'single-line-normalized', TEXT)
    focus(qa, SHORT)
    require(qa.eval("import voice_field_probe as f; result=f.active.text == 'café blue cube'"),
            'Single-line result retained controls, lost words or corrupted Unicode')
    key(qa, SHORT, 'A', oskey=True)
    hold(qa, SHORT)
    release(qa, SHORT)
    # Raw result exceeds this field's max length; normalized result fits.
    finish(qa, 'a\x07\x07\x07\x07\x07\r\nb')
    caret(qa, SHORT, 'a b')
    snapshot(qa, 'normalized-length-check', SHORT)
    focus(qa, TEXT)
    require(qa.eval("import voice_field_probe as f; result=f.active.short == 'a b'"),
            'Length check rejected a normalized result that fits')
    key(qa, TEXT, 'ESC')
    qa.press('ESC')


def multiline(qa):
    open_pill(qa)
    set_text(qa, CHAT, 'replace me')
    key(qa, CHAT, 'A', oskey=True)
    hold(qa, CHAT)
    release(qa, CHAT)
    finish(qa, 'café\r\nblue\tcube\x07\x1f\x7f')
    expected = 'café\nblue cube'
    qa.wait(f'drv.main_window().scene.mixie_chat_input == {expected!r}', timeout=5)
    caret(qa, CHAT, expected)
    require(not qa.eval('result=drv.main_window().scene.mixie_chat_is_busy'),
            'Multiline dictation auto-submitted')
    snapshot(qa, 'multiline-preserved', CHAT)
    key(qa, CHAT, 'Z', oskey=True)
    qa.wait("drv.main_window().scene.mixie_chat_input == 'replace me'", timeout=5)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    local = str(Path(__file__).resolve().parent)
    qa.eval(f'import sys; sys.path.insert(0, {local!r}); '
            'import voice_focus_probe as v; import voice_field_probe as f; '
            'v.install(); v.latest=None; f.install(); '
            'bpy.context.window_manager.mixie_chat_is_logged_in=True; result=True')
    try:
        qa.step('pending_escape_reverts_field', escape_pending, qa)
        qa.step('active_escape_preserves_field', escape_active, qa)
        qa.step('single_line_controls_unicode_and_length', single_line, qa)
        qa.step('multiline_paragraphs_and_undo', multiline, qa)
        return {'backend_calls': 0, 'capture': 'fixture', 'snapshots': str(OUT)}
    finally:
        qa.eval('import voice_focus_probe as v; import voice_field_probe as f; '
                'v.uninstall(); f.uninstall(); result=True')


if __name__ == '__main__':
    run_scenario('voice_review_fixes_e2e', run)
