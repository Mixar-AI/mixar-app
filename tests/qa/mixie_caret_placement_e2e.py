#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No paid calls: click rendered caret positions and verify UTF-8 byte indices.

Covers proportional text, blank lines, wrapping, scrolling, resize and UI scale.
The QA inspector exports native painter geometry; this test does not duplicate
font metrics or wrapping. State assertions are paired with screenshots.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario
from mixie_open_type_send_e2e import FIELD, SCENE, field, open_pill, press, snap, type_draft


def require(value, message):
    if not value:
        raise ScenarioFail(message)


def set_draft(qa, text):
    if qa.find(**FIELD)['total']:
        press(qa, 'ESC')
    qa.eval(f'{SCENE}.mixie_chat_input={text!r}; result=True')
    open_pill(qa)
    qa.wait(f'bool(drv.find_one(**{FIELD!r}).get("text_edit",{{}}).get("carets"))', timeout=4)


def click_caret(qa, point):
    f = field(qa)
    qa.cmd('click_xy', window=f['window'], x=point['x'] + 1, y=point['y'])
    data = field(qa)['text_edit']
    require(data['cursor'] == point['byte'], f'Clicked {point}, caret landed at {data}')
    require(data['selection'][0] == data['selection'][1], 'Single click selected text')


def check_text(qa, out, name, text, scrolled=False):
    set_draft(qa, text)
    data = field(qa)['text_edit']
    require(not scrolled or data['scroll'] > 0, 'Scroll fixture did not overflow')
    points = data['carets']
    # Include every line's start/end and a spread of interior glyphs.
    chosen = [p for i, p in enumerate(points) if i == 0 or i == len(points)-1 or
              p['y'] != points[i-1]['y'] or
              (i+1 < len(points) and p['y'] != points[i+1]['y']) or
              i % max(1, len(points)//20) == 0]
    for point in chosen:
        click_caret(qa, point)
    point = chosen[len(chosen)//2]
    click_caret(qa, point)
    snap(qa, out, name)
    raw = text.encode('utf-8')
    expected = (raw[:point['byte']] + b'X' + raw[point['byte']:]).decode('utf-8')
    type_draft(qa, 'X')
    actual = qa.eval(f'result={SCENE}.mixie_chat_input')
    require(actual == expected, f'{name}: inserted at the wrong character: {actual!r}')
    return len(chosen)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixie-caret-qa')) / 'snaps'
    out.mkdir(parents=True, exist_ok=True)
    scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    clicks = 0
    if qa.find(**FIELD)['total']:
        press(qa, 'ESC')
    qa.eval(f'{SCENE}.mixie_chat_messages.clear(); {SCENE}.mixie_chat_input=""; '
            "bpy.context.window_manager.mixar_bubble_tab='AGENT'; result=True")
    open_pill(qa)
    try:
        texts = [
            ('blank-lines-unicode', 'WiWi iii WWW abc\n\n\nCafé猫 text\nLast line\n', False),
            ('wrapped', 'Proportional WWW iii text. ' * 13 + '\n' + 'Wi猫' * 65, False),
            ('scrolled', '\n'.join(f'Line {n}: WiWi iii WWW Café猫 end' for n in range(40)), True),
        ]
        for width, ui_scale in ((560, 1.0), (720, 1.25)):
            qa.eval(f'bpy.context.preferences.view.ui_scale={ui_scale}; result=True')
            qa.eval(f'w=drv.find_one(**{FIELD!r})["_win"]\n'
                    'with bpy.context.temp_override(window=w):\n'
                    f'    bpy.ops.mixar.bubble_set_size(width={width},height=280)\nresult=True')
            time.sleep(.3)
            for label, text, scrolled in texts:
                name = f'{label}-{width}-{ui_scale}'
                clicks += qa.step(name, check_text, qa, out, name, text, scrolled)
        return {'caret_clicks': clicks, 'backend_calls': 0, 'snapshots': str(out)}
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')


if __name__ == '__main__':
    run_scenario('mixie_caret_placement_e2e', run)
