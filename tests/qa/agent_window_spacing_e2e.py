#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Agent header/composer spacing and native-action replay.

Run on an isolated offline Dev app with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT set. Captures empty/conversation layouts at three widths and
two interface scales; assertions read the actual native hit rectangles.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from checkpoint_rules_ui_e2e import SETUP, CLEANUP, click
from mixie_open_type_send_e2e import FIELD, SCENE, open_pill

OPS = ('show_history', 'new_session', 'show_checkpoints', 'add_rules', 'ink_toggle')
SETUP += r'''
from mixar.modules.space_mixie_chat.core import chat_history
from mixar.modules.space_mixie_chat.ui.operators import session_ops
f.history_home = chat_history._mixar_home
f.history_cache = chat_history._cached_sessions
f.cancel_request = session_ops.send_cancel_request_async
chat_history._mixar_home = lambda: f.scratch.name
chat_history._cached_sessions = None
session_ops.send_cancel_request_async = lambda session_id: None
result = True
'''
CLEANUP = r'''
from mixar.modules.space_mixie_chat.core import chat_history
from mixar.modules.space_mixie_chat.ui.operators import session_ops
f = drv._checkpoint_rules_qa
chat_history._mixar_home = f.history_home
chat_history._cached_sessions = f.history_cache
session_ops.send_cancel_request_async = f.cancel_request
''' + CLEANUP


def target(op):
    return {'area_type': 'AGENT_BUBBLE', 'op': 'MIXIE_CHAT_OT_' + op}


def rect(qa, query):
    hits = qa.find(**query)['widgets']
    assert len(hits) == 1, (query, hits)
    return hits[0]['rect']


def resize(qa, width, height):
    qa.eval(f'w=drv.find_one(**{target("show_history")!r})["_win"]\n'
            'with bpy.context.temp_override(window=w):\n'
            f'    bpy.ops.mixar.bubble_set_size(width={width},height={height})\n'
            'result=True')
    time.sleep(.5)


def capture(qa, out, name):
    path = out / (name + '.png')
    qa.eval(f'w=drv.find_one(**{target("show_history")!r})["_win"]\n'
            'with bpy.context.temp_override(window=w):\n'
            f'    result=w.mixar_qa_capture_frame(filepath={str(path)!r})')


def geometry(qa, transcript):
    buttons = [rect(qa, target(op)) for op in OPS]
    area = qa.eval(f'a=drv.find_one(**{target("show_history")!r})["_area"]; '
                   'result=[a.x,a.y,a.width,a.height]')
    x, y, width, height = area
    unit = width / 1310
    side = 24 * unit
    diameter = 44 * unit
    gaps = [buttons[i+1][0] - buttons[i][2] for i in range(3)]
    for gap in gaps:
        assert abs(gap - 16 * unit) <= 2, (gaps, unit)
    for b in buttons:
        assert abs(b[2] - b[0] - diameter) <= 2, b
        assert abs(b[3] - b[1] - diameter) <= 2, b
        assert abs(b[1] - buttons[0][1]) <= 1, buttons
    margins = [buttons[0][0] - x, x + width - buttons[-1][2]]
    assert all(abs(m - side) <= 2 for m in margins), (margins, side)
    assert buttons[3][2] + 16 * unit < buttons[4][0], buttons
    card_top = y + height - 73 * unit
    panel_top = y + height - 157 * unit
    vertical = [card_top - buttons[0][3], buttons[0][1] - panel_top]
    assert all(abs(m - 20 * unit) <= 2 for m in vertical), vertical
    field = rect(qa, FIELD)
    upload = rect(qa, target('add_image_from_file'))
    send = rect(qa, target('send_message'))
    assert abs(field[0] - buttons[0][0]) <= 2, (field, buttons)
    assert abs(field[2] - buttons[-1][2]) <= 2, (field, buttons)
    assert abs(upload[0] - field[0]) <= 2, (upload, field)
    assert abs(send[2] - field[2]) <= 2, (send, field)
    assert abs(send[1] - y - side) <= 2, (send, side)
    assert field[1] > send[3] and send[0] > upload[2], (field, send, upload)
    assert field[3] <= panel_top + 2, (field, panel_top, transcript)
    return {'size': [width, height], 'header_gaps': gaps,
            'side_padding': margins, 'header_vertical_padding': vertical,
            'button_diameter': diameter}


def actions(qa, out):
    # Opening cards exercises the real hit targets; no project is restored.
    for op, flag, close in (
        ('show_history', 'mixie_chat_history_visible', 'chat_history_close'),
        ('show_checkpoints', 'mixie_chat_history_visible', 'chat_checkpoints_close'),
        ('add_rules', 'mixie_chat_rules_visible', 'chat_rules_close'),
    ):
        click(qa, target(op))
        qa.wait(f'bpy.context.window_manager.{flag}', timeout=5)
        capture(qa, out, op)
        click(qa, {'surface': close})
        qa.wait(f'not bpy.context.window_manager.{flag}', timeout=5)
    click(qa, target('ink_toggle'))
    qa.wait('bpy.context.window_manager.mixie_chat_ink_visible', timeout=5)
    capture(qa, out, 'handwriting')
    click(qa, target('ink_toggle'))
    qa.wait('not bpy.context.window_manager.mixie_chat_ink_visible', timeout=5)
    qa.wait(f'{SCENE}.mixie_chat_input == "Spacing review draft"', timeout=5)
    click(qa, target('new_session'))
    qa.wait(f'len({SCENE}.mixie_chat_messages)==0 and not {SCENE}.mixie_chat_input',
            timeout=5)
    assert qa.eval('from mixar.modules.space_mixie_chat.core import chat_history; '
                   'result=len(chat_history.list_sessions(""))') == 1


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.types.WindowManager,'mixie_chat_rule_entries')", timeout=30)
    saved_scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    qa.step('isolated_local_stores', qa.eval, SETUP)
    metrics = {}
    try:
        open_pill(qa)
        for scale in (1.0, 1.25):
            qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
            for transcript in (False, True):
                qa.eval(f's={SCENE}; s.mixie_chat_messages.clear()\n'
                        + ('m=s.mixie_chat_messages.add(); m.sender="USER"; '
                           'm.text="Review the agent window spacing"\n' if transcript else '')
                        + 's.mixie_chat_input="Spacing review draft"; result=True')
                for width in (560, 678, 1100):
                    resize(qa, width, 407 if transcript else max(230, round(width * .28)))
                    name = f'{"conversation" if transcript else "empty"}-{width}-{scale}'
                    metrics[name] = qa.step(name, geometry, qa, transcript)
                    capture(qa, out, name)
        qa.eval('bpy.context.preferences.view.ui_scale=1.0; result=True')
        resize(qa, 678, 407)
        qa.step('all_five_header_actions', actions, qa, out)
        return {'geometry': metrics, 'backend_calls': 0, 'screenshots': str(out)}
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved_scale}; result=True')
        qa.eval(CLEANUP)


if __name__ == '__main__':
    run_scenario('agent_window_spacing_e2e', run)
