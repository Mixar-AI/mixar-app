#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No paid calls: empty hover, outside press, resize persistence and trackpad scrolling.

Run against an isolated macOS Dev app with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT set. Physical OS snipping and trackpad hardware remain separate manual checks.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario
from mixie_open_type_send_e2e import FIELD, SCENE, TRANSCRIPT, field, open_pill, press, scroll_y, snap, type_draft, warp


def require(value, message):
    if not value:
        raise ScenarioFail(message)


def native(qa):
    return qa.eval('import mixie_window_native as n; result=n.windows()')


def visible(qa):
    return any(w['is_island'] and w['visible'] for w in native(qa))


def host_event(qa, key='LEFTMOUSE', value='PRESS'):
    qa.eval('w=drv.main_window(); '
            "r=next(r for a in w.screen.areas if a.type=='VIEW_3D' for r in a.regions if r.type=='WINDOW'); "
            'x=r.x+50; y=r.y+r.height-50; w.cursor_warp(x,y); '
            f'w.event_simulate(type={key!r},value={value!r},x=x,y=y); result=True')


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixie-window-qa')) / 'snaps'
    out.mkdir(parents=True, exist_ok=True)
    qa.eval(f'import sys, importlib; sys.path.insert(0,{str(Path(__file__).parent)!r}); '
            'import mixie_window_native as n; importlib.reload(n); result=True')
    if qa.find(**FIELD)['total']:
        press(qa, 'ESC')
    qa.eval(f'scene={SCENE}; scene.mixie_chat_input=""; '
            'scene.mixie_chat_messages.clear(); result=True')
    open_pill(qa)
    warp(qa, FIELD)
    time.sleep(.25)
    host_event(qa, 'MOUSEMOVE', 'NOTHING')
    time.sleep(.7)
    require(visible(qa), 'empty chat collapsed on pointer exit')
    host_event(qa, 'WHEELUPMOUSE')
    time.sleep(.3)
    require(visible(qa), 'scrolling outside collapsed chat')
    snap(qa, out, 'empty-stays-open')
    qa.step('empty_chat_survives_pointer_exit_and_scroll', lambda: True)

    host_event(qa)
    host_event(qa, value='RELEASE')
    time.sleep(.4)
    require(not visible(qa), 'outside click did not collapse')
    qa.step('outside_click_collapses', lambda: True)
    open_pill(qa)
    limits = next(w for w in native(qa) if w['is_island'])
    require(limits['max_height'] > 1000, f'preset still caps height: {limits}')
    qa.eval(f'w=drv.find_one(**{FIELD!r})["_win"]\n'
            'with bpy.context.temp_override(window=w):\n'
            '    bpy.ops.mixar.bubble_set_size(width=640,height=520)\nresult=True')
    time.sleep(.35)
    size = qa.eval(f'w=drv.find_one(**{FIELD!r})["_win"]; result=[w.width,w.height]')
    require(size == [640, 520], f'could not increase height: {size}')
    open_pill(qa)
    after = qa.eval(f'w=drv.find_one(**{FIELD!r})["_win"]; result=[w.width,w.height]')
    require(after == size, f'reopen discarded user size: {after}')
    snap(qa, out, 'taller-chat-reopened')
    qa.step('taller_size_survives_reopen', lambda: True)

    text='\n\n'.join(f'Paragraph {i}: test trackpad scrolling in a taller chat.' for i in range(65))
    qa.eval(f'scene={SCENE}; m=scene.mixie_chat_messages.add(); '
            "m.sender='AGENT'; m.message_type='AGENT'; m.bubble_id='qa-taller-scroll'; "
            f'm.content={text!r}; result=True')
    time.sleep(.3)
    open_pill(qa)
    type_draft(qa, 'Trackpad scroll still works')
    qa.wait(f'{SCENE}.mixie_chat_input == "Trackpad scroll still works"', timeout=4)
    before=scroll_y(qa)
    qa.eval(TRANSCRIPT + 'x=r.x+r.width//2; y=r.y+r.height//2; '
            "w.event_simulate(type='MOUSEMOVE',value='NOTHING',x=x,y=y+90); result=True")
    qa.eval(TRANSCRIPT + 'x=r.x+r.width//2; y=r.y+r.height//2; '
            "w.event_simulate(type='TRACKPADPAN',value='NOTHING',x=x,y=y); result=True")
    time.sleep(.25)
    require(scroll_y(qa) != before, 'trackpad did not scroll the transcript')
    snap(qa,out,'trackpad-scroll')
    qa.step('trackpad_scroll_with_taller_chat',lambda: True)
    return {'size': after, 'snapshots':str(out), 'backend_calls':0}



if __name__=='__main__':
    run_scenario('mixie_window_interaction_e2e', run)
