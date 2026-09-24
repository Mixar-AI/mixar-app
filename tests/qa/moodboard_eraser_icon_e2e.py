#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit eraser glyph/state replay on the drawer and standalone canvas.

Run on a fresh isolated QA scene with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT set. Inspect the toolbar crops for a filled tilted block eraser with a narrow transparent dividing line
and the full-board captures for the erased stroke, plus the JSON verdict.
"""

from moodboard_annotations_e2e import (
    ACTIVE, ERASING, STROKES, draw, erase_stroke, set_erase, set_mode,
)
from moodboard_drawer_e2e import OUT, geometry, run_scenario, toggle


def capture(qa, host, selected):
    query = {'area_type': host, 'op': 'MIXIE_OT_moodboard_erase_canvas'}
    widget = qa.find(**query)['widgets'][0]
    assert widget['enabled'] and widget['mixar_component'] == 'action', widget
    assert widget['mixar_theme'] == 'ZEN' and not widget['text'], widget
    qa.wait(f"abs(drv.find_one(**{query!r})['mixar_motion']['selected']"
            f"-{int(selected)}) < .002", timeout=4)
    assert qa.eval(f'result={ERASING}') == selected
    qa.cmd('snap', path=str(OUT / f'{host}-eraser-{int(selected)}.png'),
           target=query, margin=55)
    qa.cmd('snap', path=str(OUT / f'{host}-board-{int(selected)}.png'), area=host)
    return widget


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    assert qa.eval("import os; result=os.environ.get('MIXAR_QA') == '1'")
    qa.cmd('wait_login', timeout=90)
    qa.dismiss_splash()
    assert qa.eval(f'result=len({STROKES})') == 0, 'Use a fresh isolated QA scene'
    if geometry(qa)['workspace'] != 'Zen Mode':
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    qa.step('annotate', set_mode, qa, True)
    qa.step('first_stroke', draw, qa)
    qa.step('second_stroke', draw, qa, offset=.12)
    qa.step('exit_annotate', set_mode, qa, False)
    qa.step('drawer_eraser_icon', capture, qa, 'VIEW_3D', False)
    qa.step('enable_erase', set_erase, qa, True)
    qa.step('drawer_selected_icon', capture, qa, 'VIEW_3D', True)
    qa.step('erase_stroke', erase_stroke, qa)
    assert qa.eval(f'result=len({STROKES})') == 1
    qa.step('exit_erase', set_erase, qa, False)
    qa.step('close_drawer', toggle, qa, 0)
    qa.cmd('ensure_moodboard', sidebar=False)
    query = {'area_type': 'MIXIE', 'op': 'MIXIE_OT_moodboard_erase_canvas'}
    qa.wait(f'bool(drv.find(**{query!r}))', timeout=5)
    qa.step('editor_eraser_icon', capture, qa, 'MIXIE', False)
    qa.click(**query)
    qa.step('editor_selected_icon', capture, qa, 'MIXIE', True)
    assert not qa.eval(f'result={ACTIVE}')
    qa.click(**query)
    qa.step('editor_deselected_icon', capture, qa, 'MIXIE', False)
    return {'backend_submissions': 0, 'screenshots': str(OUT), 'remaining_strokes': 1}


if __name__ == '__main__':
    run_scenario('moodboard_eraser_icon_e2e', run)
