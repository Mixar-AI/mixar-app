#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit replay for the Zen drawer Clear chip.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT, then run this file.
The Mixie header Clear is a separate host; this scenario stays in Zen Mode.
"""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
sys.path.insert(0, str(Path(__file__).parent))
from moodboard_drawer_e2e import geometry, target, toggle
from moodboard_drawer_tools_e2e import text_placement


OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-drawer-clear'))
CLEAR = {'region_type': 'TOOL_PROPS', 'op': 'MIXIE_OT_clear_moodboard'}
TEXT = {'region_type': 'TOOL_PROPS', 'op': 'MIXIE_OT_moodboard_add_textbox'}
SCENE = 'drv.main_window().scene'
COLLECTIONS = ('images', 'textboxes', 'groups', 'action_nodes', 'asset_nodes',
               'links', 'annotations')
EMPTY = f'all(not getattr({SCENE}, "mixie_moodboard_" + n) for n in {COLLECTIONS!r})'
BOXES = f'{SCENE}.mixie_moodboard_textboxes'


def snap(qa, name, annotated=False):
    time.sleep(.3)
    args = {'path': str(OUT / f'{name}.png'),
            'target': {'surface': 'moodboard_drawer_panel'}, 'margin': 48}
    if annotated:
        args['annotate'] = CLEAR
    return qa.cmd('snap', **args)


def assert_hidden(qa):
    assert not qa.find(**CLEAR)['total']


def assert_visible(qa):
    found = qa.find(**CLEAR)
    assert found['total'] == 1, found
    widget = found['widgets'][0]
    panel = target(qa, 'moodboard_drawer_panel')['rect']
    x0, y0, x1, y1 = widget['rect']
    assert widget['enabled'] and widget['mixar_theme'] == 'ZEN', widget
    assert widget['mixar_component'] == 'action', widget
    assert widget['block'] == 'moodboard_drawer_clear', widget
    assert widget['text'] == 'Clear', widget
    assert panel[0] < x0 < x1 < panel[2], (widget, panel)
    assert panel[1] < y0 < y1 < panel[3], (widget, panel)
    text = qa.find(**TEXT)['widgets']
    assert len(text) == 1, text
    left = text[0]['rect']
    assert x0 > left[2], (widget, text[0])
    assert abs(y1 - left[3]) <= 8, (widget, text[0])
    return widget


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    if geometry(qa)['workspace'] != 'Zen Mode':
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .998', timeout=4)
    qa.step('empty_hides_clear', assert_hidden, qa)
    qa.step('empty_default', snap, qa, '01-empty')
    qa.step('add_text', text_placement, qa)
    qa.wait(f'len({BOXES}) == 1', timeout=4)
    qa.step('occupied_shows_clear', assert_visible, qa)
    qa.step('occupied_screenshot', snap, qa, '02-clear-visible', True)
    qa.step('clear_board', qa.click, **CLEAR)
    qa.wait(EMPTY, timeout=4)
    qa.step('cleared_hides_clear', assert_hidden, qa)
    qa.step('cleared_screenshot', snap, qa, '03-cleared')
    modifier = {'oskey': True} if sys.platform == 'darwin' else {'ctrl': True}
    qa.press('Z', **modifier)
    qa.wait(f'len({BOXES}) == 1', timeout=5)
    qa.step('undo_restores_clear', assert_visible, qa)
    qa.step('undo_screenshot', snap, qa, '04-undo')
    return {'backend_submissions': 0, 'screenshots': str(OUT)}


if __name__ == '__main__':
    run_scenario('moodboard_drawer_clear_e2e', run)
