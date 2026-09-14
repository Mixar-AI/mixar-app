#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Composer drag-selection with and without focus; no backend or clipboard calls.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT against an isolated Dev app.
Endpoints come from the live input rectangle; no screen-coordinate guesses.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario
from mixie_open_type_send_e2e import FIELD, SCENE, field, open_pill, press, snap, type_draft


DRAFT = 'Select these words\nAnd this second line\n'


def require(value, message):
    if not value:
        raise ScenarioFail(message)


def frame(qa):
    return qa.eval('import mixie_window_native as n; '
                   "result=next([w['x'],w['y'],w['width'],w['height']] "
                   "for w in n.windows() if w['is_island'] and w['visible'])")


def select_all_by_drag(qa):
    f = field(qa)
    x0, y0, x1, y1 = f['rect']
    before = frame(qa)
    qa.cmd('drag', **{
        'from': {'window': f['window'], 'x': x0 + 1, 'y': y1 - 1},
        'to': {'window': f['window'], 'x': x1 - 1, 'y': y0 + 1},
    })
    require(frame(qa) == before, 'Selecting text moved or resized the window')


def selection_case(qa, out, label, focused):
    press(qa, 'ESC')
    qa.eval(f'{SCENE}.mixie_chat_input={DRAFT!r}; result=True')
    if focused:
        open_pill(qa)
    time.sleep(.2)
    select_all_by_drag(qa)
    snap(qa, out, label)
    type_draft(qa, 'Selection replaced')
    actual = qa.eval(f'result={SCENE}.mixie_chat_input')
    require(actual == 'Selection replaced', f'{label}: selection was lost: {actual!r}')


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixie-selection-qa')) / 'snaps'
    out.mkdir(parents=True, exist_ok=True)
    qa.eval(f'import sys; sys.path.insert(0,{str(Path(__file__).parent)!r}); result=True')
    if qa.find(**FIELD)['total']:
        press(qa, 'ESC')
    qa.eval(f'scene={SCENE}; scene.mixie_chat_messages.clear(); '
            "scene.mixie_chat_input=''; scene.mixie_chat_mode='AGENT'; "
            "bpy.context.window_manager.mixar_bubble_tab='AGENT'; result=True")
    open_pill(qa)
    qa.eval(f'w=drv.find_one(**{FIELD!r})["_win"]\n'
            'with bpy.context.temp_override(window=w):\n'
            '    bpy.ops.mixar.bubble_set_size(width=640,height=520)\nresult=True')
    require(not qa.eval('import mixie_window_native as n; '
                        "result=any(w['background_draggable'] for w in n.windows() if w['is_island'])"),
            'Cocoa can drag the window behind the text handler')
    for has_messages in (False, True):
        label = 'conversation' if has_messages else 'empty'
        if has_messages:
            press(qa, 'ESC')
            qa.eval(f'm={SCENE}.mixie_chat_messages.add(); '
                    "m.sender='AGENT'; m.message_type='AGENT'; m.bubble_id='qa-selection'; "
                    "m.content='A local reply above the editable composer.'; result=True")
            open_pill(qa)
        expected = 'TOOLS' if has_messages else 'WINDOW'
        qa.wait(f'drv.find_one(**{FIELD!r})["region_type"] == {expected!r}', timeout=3)
        for focused in (True, False):
            case = f'{label}-' + ('focused' if focused else 'first-drag')
            qa.step(case, selection_case, qa, out, case, focused)
        # Direct native calls must obey the same boundary as the Python binding.
        result = qa.eval(f'w=drv.find_one(**{FIELD!r})["_win"]\n'
                         "a=next(a for a in w.screen.areas if a.type=='AGENT_BUBBLE')\n"
                         f'r=next(r for r in a.regions if r.type=={expected!r})\n'
                         'with bpy.context.temp_override(window=w,area=a,region=r):\n'
                         '    result=list(bpy.ops.mixar.bubble_window_begin_drag())')
        require(result == ['CANCELLED'], f'Native drag accepted {expected}: {result}')
    return {'backend_calls': 0, 'snapshots': str(out)}


if __name__ == '__main__':
    run_scenario('mixie_text_selection_e2e', run)
