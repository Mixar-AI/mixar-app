#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Picking another canvas tool releases the sticky Annotate/Erase pencil.

Reproduces the report "Annotate never ends": Annotate on, click the Text
tool, place and type a text box, click anywhere else -- the click must select
(or deselect) like a normal click, never start a new stroke. Also covers the
Erase tool handing off to Text and an image mask tool releasing the pencil.

No credits. Set QA_HARNESS and QA_SCENARIO_OUT; run against an isolated QA app.
"""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
sys.path.insert(0, str(Path(__file__).parent))
from moodboard_drawer_e2e import drop, geometry, png, point, target, toggle
from moodboard_drawer_tools_e2e import ANNOTATE, BOXES, TEXT
from moodboard_annotations_e2e import ACTIVE, ERASING, STROKES, draw, set_erase, set_mode, strokes

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-annotate-tool-switch'))
MASK_MENU = {'region_type': 'TOOL_PROPS', 'text': 'Image mask selection tools'}
TOOL = 'drv.main_window().scene.mixie_edit_tool_state.active_tool'


def capture(qa, name):
    time.sleep(.25)
    return qa.cmd('snap', path=str(OUT / f'{name}.png'),
                  target={'surface': 'moodboard_drawer_panel'}, margin=48)


def pencil_released(qa):
    qa.wait(f'not {ACTIVE} and not {ERASING}', timeout=4)
    qa.wait(f"drv.find_one(**{ANNOTATE!r})['mixar_motion']['selected'] < .002", timeout=4)


def text_tool_releases_annotate(qa):
    before = strokes(qa)
    count = qa.eval(f'result=len({BOXES})')
    assert qa.eval(f'result={ACTIVE}')
    qa.click(**TEXT)
    qa.wait(f'len({BOXES}) == {count + 1}', timeout=4)  # Sample box follows the cursor.
    pencil_released(qa)
    # Place the box with a real click; the pencil is off, so no stroke either.
    pos = point(target(qa, 'moodboard_drawer_panel'), .6, .4)
    qa.cmd('click_xy', **pos)
    time.sleep(.3)
    assert strokes(qa) == before, strokes(qa)
    assert qa.eval(f'result=len({BOXES})') == count + 1
    assert qa.eval(f'result={BOXES}[-1].selected')
    capture(qa, '01-text-placed')


def edit_text_then_click_elsewhere(qa):
    before = strokes(qa)
    center = qa.eval('''
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='VIEW_3D')
drawer=next(r for r in area.regions if r.type=='TOOL_PROPS')
tb=win.scene.mixie_moodboard_textboxes[-1]
x,y=drawer.view2d.view_to_region(tb.position_x+tb.width/2, tb.position_y+tb.height/2)
result={'x':drawer.x+x,'y':drawer.y+y}
''')
    qa.cmd('click_xy', **center)
    # Simulated events never form a double-click; the context-menu action
    # runs the same edit operator.
    qa.press('RIGHTMOUSE')
    qa.click(popup=True, op='MIXIE_OT_moodboard_edit_textbox')
    qa.wait(f"{BOXES}[-1].text.endswith('|')", timeout=4)
    qa.cmd('type', text='Annotate is off')
    qa.press('RET')
    qa.wait(f"{BOXES}[-1].text == 'Annotate is off'", timeout=4)
    # The report: this click used to start a stroke. It must be a plain
    # canvas click that only clears the selection.
    qa.cmd('click_xy', **point(target(qa, 'moodboard_drawer_panel'), .25, .8))
    time.sleep(.4)
    assert strokes(qa) == before, strokes(qa)
    assert not qa.eval(f'result={ACTIVE}')
    qa.wait(f'not {BOXES}[-1].selected', timeout=4)
    # And a drag is a box-select / pan gesture, never a stroke.
    panel = target(qa, 'moodboard_drawer_panel')
    qa.cmd('drag', **{'from': point(panel, .2, .7), 'to': point(panel, .4, .9), 'steps': 8})
    time.sleep(.3)
    assert strokes(qa) == before, strokes(qa)
    capture(qa, '02-click-elsewhere-no-stroke')


def text_tool_releases_erase(qa):
    count = qa.eval(f'result=len({BOXES})')
    set_erase(qa, True)
    qa.click(**TEXT)
    qa.wait(f'len({BOXES}) == {count + 1}', timeout=4)
    pencil_released(qa)
    qa.press('ESC')  # Cancel placement; the released mode must stay released.
    qa.wait(f'len({BOXES}) == {count}', timeout=4)
    assert not qa.eval(f'result={ERASING}')


def image_tool_releases_annotate(qa):
    path = png(OUT / 'reference.png', (90, 120, 150), width=300, height=200)
    node_id = drop(qa, path, target={'surface': 'moodboard_drawer_panel'})
    # A real click selects the reference; the toolbar enables its mask tools.
    qa.click(surface='moodboard_media', text=node_id)
    qa.wait(f"drv.find_one(**{MASK_MENU!r})['enabled']", timeout=4)
    set_mode(qa, True)
    before = strokes(qa)
    qa.click(**MASK_MENU)
    qa.wait("bool(drv.find(popup=True, op='MIXIE_OT_moodboard_box_mask_tool'))", timeout=4)
    capture(qa, '03-mask-menu-while-annotating')
    qa.click(popup=True, op='MIXIE_OT_moodboard_box_mask_tool')
    qa.wait(f"{TOOL} == 'BOX_MASK'", timeout=4)
    pencil_released(qa)
    qa.press('ESC')
    qa.wait(f"{TOOL} == 'NONE'", timeout=4)
    assert strokes(qa) == before
    assert not qa.eval(f'result={ACTIVE}')
    capture(qa, '04-after-mask-tool')


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    assert qa.eval("import os; result=os.environ.get('MIXAR_QA') == '1'")
    assert not strokes(qa), 'Run in a fresh isolated QA scene'
    if geometry(qa)['workspace'] != 'Zen Mode':
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    original = geometry(qa)
    qa.step('enable_annotation', set_mode, qa, True)
    qa.step('draw_stroke', draw, qa)
    qa.step('text_tool_releases_annotate', text_tool_releases_annotate, qa)
    qa.step('edit_text_then_click_elsewhere', edit_text_then_click_elsewhere, qa)
    qa.step('text_tool_releases_erase', text_tool_releases_erase, qa)
    qa.step('image_tool_releases_annotate', image_tool_releases_annotate, qa)
    qa.step('annotate_still_works_afterwards', set_mode, qa, True)
    qa.step('draw_after_switches', draw, qa, offset=.15)
    qa.step('exit_with_esc', qa.press, 'ESC')
    qa.wait(f'not {ACTIVE}', timeout=4)
    after = geometry(qa)
    for key in ('viewport', 'view', 'objects'):
        assert after[key] == original[key], (key, original[key], after[key])
    return {'steps': qa.log, 'paid_requests': 0, 'strokes': len(strokes(qa)),
            'viewport_unchanged': True, 'screenshots': str(OUT)}


if __name__ == '__main__':
    run_scenario('moodboard_annotate_tool_switch_e2e', run)
