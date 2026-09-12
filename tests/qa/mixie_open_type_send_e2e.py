#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pill -> type -> Send/Enter in the REAL app, with no backend calls.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4795 \
  QA_SCENARIO_OUT=/tmp/mixie-open-qa python3 tests/qa/mixie_open_type_send_e2e.py

Use an isolated profile with external networking blocked. The fixture probes
the transport boundary; it exercises native events, the real send operator,
draft clearing, optimistic history and busy state. Inspect every saved PNG.
Hover stays enabled; cursor_warp follows the semantic native-window target.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

FIELD = {'area_type': 'AGENT_BUBBLE', 'prop': 'mixie_chat_input'}
SEND = {'area_type': 'AGENT_BUBBLE', 'op': 'MIXIE_CHAT_OT_send_message'}
SCENE = 'drv.main_window().scene'


def warp(qa, query):
    qa.eval(f'w = drv.find_one(**{query!r}); x,y = drv.pick_click_point(w); '
            "w['_win'].cursor_warp(x,y); result = True")


def field(qa):
    return qa.find(**FIELD)['widgets'][0]


def type_draft(qa, text):
    qa.cmd('type', window=field(qa)['window'], text=text)


def press(qa, key, **mods):
    qa.press(key, window=field(qa)['window'], **mods)


def draft_is(qa, text):
    qa.wait(f'{SCENE}.mixie_chat_input == {text!r}', timeout=4)


def snap(qa, out, name):
    # State is available before the native 0.26s entrance animation presents
    # its first complete window frame. Keep typing immediate; capture after
    # the transition so screenshots do not read the initial grey swapchain.
    time.sleep(.35)
    qa.cmd('snap', path=str(out / f'{name}.png'), target=FIELD, margin=1500)


def open_pill(qa):
    qa.eval('result = str(bpy.ops.mixar.bubble_minimise())')
    qa.wait("bool(drv.find(surface='pill_cat'))", timeout=5)
    # event_simulate bypasses AppKit activation. A real click on the pill
    # activates its app before restore; reproduce that prerequisite locally.
    qa.eval(
        'import sys\n'
        "if sys.platform == 'darwin':\n"
        '    import ctypes as ct\n'
        "    objc=ct.CDLL('/usr/lib/libobjc.A.dylib')\n"
        '    objc.objc_getClass.restype=ct.c_void_p\n'
        '    objc.sel_registerName.restype=ct.c_void_p\n'
        '    send=ct.CFUNCTYPE(ct.c_void_p,ct.c_void_p,ct.c_void_p)(\n'
        "        ('objc_msgSend',objc))\n"
        "    app=send(objc.objc_getClass(b'NSApplication'),objc.sel_registerName(b'sharedApplication'))\n"
        "    activate=ct.CFUNCTYPE(None,ct.c_void_p,ct.c_void_p,ct.c_bool)(('objc_msgSend',objc))\n"
        "    activate(app,objc.sel_registerName(b'activateIgnoringOtherApps:'),True)\n"
        'result=True'
    )
    warp(qa, {'surface': 'pill_cat'})
    qa.click(surface='pill_cat')
    # No composer click or simulated move into it before typing.
    qa.wait("bool(drv.find(prop='mixie_chat_input', area_type='AGENT_BUBBLE'))", timeout=5)


def assert_sent(qa, expected, count):
    qa.wait(f'len(__import__("chat_send_probe").calls) == {count}', timeout=4)
    data = qa.eval(
        'import chat_send_probe as probe\n'
        f'scene = {SCENE}\n'
        "result = {'draft': scene.mixie_chat_input, 'busy': scene.mixie_chat_is_busy, "
        "'users': [m.text for m in scene.mixie_chat_messages if m.sender == 'USER'], "
        "'payload': probe.calls[-1]['message']}"
    )
    if (data['draft'] or not data['busy'] or len(data['users']) != count or
            data['users'][-1] != expected):
        raise ScenarioFail(f'incorrect send state: {data}')
    if expected not in data['payload'] or '\x1f' in data['payload']:
        raise ScenarioFail(f'payload lost/corrupted the draft: {data}')
    time.sleep(.3)
    if qa.eval('import chat_send_probe as p; result = len(p.calls)') != count:
        raise ScenarioFail('one action dispatched more than once')


def settle(qa):
    qa.eval(f'import chat_send_probe as p; p.settle({SCENE}); result=True')


TRANSCRIPT = (
    "w=drv.find_one(prop='mixie_chat_input', area_type='AGENT_BUBBLE')['_win']\n"
    "a=next(a for a in w.screen.areas if a.type=='AGENT_BUBBLE')\n"
    "r=next(r for r in a.regions if r.type=='WINDOW')\n"
)


def scroll_y(qa):
    return qa.eval(TRANSCRIPT + 'result = r.view2d.region_to_view(0, 0)[1]')


def scroll_with_composer_focused(qa, out):
    content = '\n\n'.join(f'Scroll check paragraph {n}: keep the composer editable.'
                          for n in range(40))
    qa.eval(f'scene={SCENE}; m=scene.mixie_chat_messages.add(); '
            "m.sender='AGENT'; m.message_type='AGENT'; m.bubble_id='qa-scroll'; "
            f'm.content={content!r}; result=True')
    open_pill(qa)
    type_draft(qa, 'Scroll while writing')
    time.sleep(.3)
    before = scroll_y(qa)
    # The transcript has no whole-region semantic target. Use its own RNA
    # rectangle, not guessed pixels, and move without a field-blurring click.
    qa.eval(TRANSCRIPT + 'x=r.x+r.width//2; y=r.y+r.height//2; '
            'w.cursor_warp(x,y); drv.move_to(w,x,y); result=True')
    press(qa, 'WHEELUPMOUSE')
    qa.wait("any(r.view2d.region_to_view(0,0)[1] != " + repr(before) +
            " for w in bpy.context.window_manager.windows "
            f"if w.as_pointer()=={field(qa)['window']} "
            "for a in w.screen.areas for r in a.regions if r.type=='WINDOW')", timeout=3)
    type_draft(qa, ' still works')
    draft_is(qa, 'Scroll while writing still works')
    transcript_y = scroll_y(qa)
    qa.eval(f'w=drv.find_one(**{FIELD!r}); x,y=drv.pick_click_point(w); '
            "w['_win'].cursor_warp(x,y); drv.move_to(w['_win'],x,y); result=True")
    press(qa, 'WHEELUPMOUSE')
    time.sleep(.2)
    if scroll_y(qa) != transcript_y:
        raise ScenarioFail('scroll over the composer moved the transcript')
    snap(qa, out, 'scroll-while-editing')


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixie-open-qa')) / 'snaps'
    out.mkdir(parents=True, exist_ok=True)
    local = str(Path(__file__).resolve().parent)
    qa.eval(f'import sys; sys.path.insert(0, {local!r}); '
            'import chat_send_probe as p; p.install(); result=True')
    try:
        # End any editor left by an earlier scenario before replacing RNA
        # fixture values; otherwise its saved buffer can overwrite the reset.
        if qa.find(**FIELD)['total']:
            press(qa, 'ESC')
        qa.eval('result=str(bpy.ops.mixar.bubble_minimise())')
        qa.wait("bool(drv.find(surface='pill_cat'))", timeout=5)
        qa.eval(f'scene = {SCENE}; scene.mixie_chat_messages.clear(); '
                "scene.mixie_chat_input=''; scene.mixie_chat_mode='AGENT'; "
                "bpy.context.window_manager.mixar_bubble_tab='AGENT'; result=True")
        qa.step('click_pill_opens_chat', open_pill, qa)
        first = 'Make a small blue cube'
        qa.step('type_without_clicking_composer', type_draft, qa, first)
        qa.step('immediate_typing_is_kept', draft_is, qa, first)
        qa.step('opened_draft_picture', snap, qa, out, 'opened-draft')

        # Visit then leave with the NATIVE cursor, so the hover latch really
        # clears. Typing must continue with the pointer over the host window.
        warp(qa, FIELD)
        time.sleep(.25)
        qa.eval('w=drv.main_window(); w.cursor_warp(40, w.height-40); result=True')
        time.sleep(.6)
        qa.step('draft_keeps_island_visible', qa.wait,
                "not drv.find(surface='pill_cat')", timeout=2)
        qa.step('typing_survives_pointer_leaving', type_draft, qa, ' please')
        first += ' please'
        qa.step('draft_survives_pointer_leaving', draft_is, qa, first)
        warp(qa, SEND)
        qa.step('one_send_click_while_editing', qa.click, **SEND)
        qa.step('click_dispatches_once_and_clears', assert_sent, qa, first, 1)
        qa.step('sent_message_visible', snap, qa, out, 'sent-click')
        settle(qa)

        qa.step('reopen_conversation', open_pill, qa)
        second = 'Make it green'
        qa.step('type_followup_without_field_click', type_draft, qa, second)
        qa.step('followup_kept', draft_is, qa, second)
        press(qa, 'HOME')
        type_draft(qa, 'Please ')
        qa.step('enter_from_middle_of_draft', press, qa, 'RET')
        qa.step('enter_dispatches_full_draft_once', assert_sent, qa, 'Please ' + second, 2)
        settle(qa)

        qa.step('reopen_for_multiline', open_pill, qa)
        type_draft(qa, 'First line')
        qa.step('shift_enter_adds_newline', press, qa, 'RET', shift=True)
        type_draft(qa, 'Second line')
        qa.step('multiline_draft_kept', draft_is, qa, 'First line\nSecond line')
        if qa.eval('import chat_send_probe as p; result=len(p.calls)') != 2:
            raise ScenarioFail('Shift+Enter submitted the message')
        qa.step('multiline_picture', snap, qa, out, 'multiline')

        qa.step('minimise_and_reopen_preserves_draft', open_pill, qa)
        type_draft(qa, ' retained')
        third = 'First line\nSecond line retained'
        qa.step('reopen_appends_without_selecting_draft', draft_is, qa, third)
        warp(qa, SEND)
        qa.step('one_click_send_from_footer_field', qa.click, **SEND)
        qa.step('footer_dispatches_once', assert_sent, qa, third, 3)
        settle(qa)
        qa.step('final_conversation_picture', snap, qa, out, 'conversation')

        qa.step('reopen_for_connection_failure', open_pill, qa)
        type_draft(qa, 'Keep this draft if disconnected')
        qa.eval('import chat_send_probe as p; p.connected=False; result=True')
        warp(qa, SEND)
        qa.step('send_while_disconnected', qa.click, **SEND)
        qa.step('failed_send_preserves_draft', draft_is, qa, 'Keep this draft if disconnected')
        if qa.eval('import chat_send_probe as p; result=len(p.calls)') != 3:
            raise ScenarioFail('disconnected message reached transport')
        qa.step('failure_picture', snap, qa, out, 'disconnected-draft')
        qa.eval('import chat_send_probe as p; p.connected=True; result=True')
        # Dismiss the native error report before retrying through the UI.
        if qa.find(popup=True, window=field(qa)['window'])['total']:
            qa.step('dismiss_error_report', press, qa, 'ESC')
        warp(qa, SEND)
        qa.step('retry_send_once', qa.click, **SEND)
        qa.step('retry_uses_preserved_draft', assert_sent, qa, 'Keep this draft if disconnected', 4)
        settle(qa)
        qa.step('scroll_preserves_text_focus_and_pointer_target',
                scroll_with_composer_focused, qa, out)
        return {'send_count': 4, 'backend_calls': 0, 'hover_enabled': True,
                'snapshots': str(out), 'platform': qa.eval('import sys; result=sys.platform')}
    finally:
        qa.eval('import chat_send_probe as p; p.uninstall(); result=True')


if __name__ == '__main__':
    run_scenario('mixie_open_type_send_e2e', run)
