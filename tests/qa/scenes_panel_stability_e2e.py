#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit stress replay: rapid Add, overflowing selection and fixed header.

Run after startup health on a clean isolated QA file with one scene.
"""
import inspect
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from scenes_panel_edit_e2e import capture, rapid_add, modified_click, hover_card

WM = 'bpy.context.window_manager'


def scroll_to_bottom():
    win = drv.main_window()
    card = drv.find(surface='scenes_drawer_card')[-1]
    drv.move_to(win, *drv.pick_click_point(card))
    yield .05
    for _ in range(20):
        drv._sim(win, type='WHEELDOWNMOUSE', value='PRESS')
        yield .02
    return True


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/scenes-stability-qa')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.dismiss_splash()
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\nresult=True")
    qa.wait(f'len({WM}.mixar_scene_tabs)==1')
    if qa.eval(f'result={WM}.mixar_scenes_drawer_amount<.98'):
        qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
    qa.wait(f'{WM}.mixar_scenes_drawer_amount>=.98')
    helpers = '\n'.join(inspect.getsource(fn) for fn in
                        (rapid_add, modified_click, hover_card, scroll_to_bottom))
    native_eval = qa.eval
    qa.eval = lambda code: native_eval(helpers + '\n' + code)
    qa.step('twelve_rapid_adds_publish_each_click', qa.eval, 'result=rapid_add(12)')
    capture(qa, out / 'rapid-added.png')
    qa.eval('result=scroll_to_bottom()')
    rects = qa.eval("result={c['text']: c['rect'] for c in drv.find(surface='scenes_drawer_card')}")
    assert len(rects) < 13, 'List must overflow to exercise off-screen selection'
    last = next(reversed(rects))
    qa.eval(f'result=modified_click({last!r}, "ctrl")')
    qa.step('selection_does_not_shift_scrolled_list', qa.eval,
            f"assert {{c['text']:c['rect'] for c in drv.find(surface='scenes_drawer_card')}}=={rects!r}\nresult=True")
    capture(qa, out / 'selected-at-bottom.png')
    qa.click(surface='scenes_drawer_clear_selection')
    qa.step('clearing_selection_does_not_shift_scrolled_list', qa.eval,
            f"assert {{c['text']:c['rect'] for c in drv.find(surface='scenes_drawer_card')}}=={rects!r}\n"
            "assert drv.find(surface='scenes_drawer_new')\nresult=True")
    qa.eval(f'result=hover_card({last!r})')
    qa.press('A', oskey=True)
    qa.wait("drv.find_one(surface='scenes_drawer_delete_selected')['value']=='13'")
    capture(qa, out / 'all-selected.png')
    qa.click(surface='scenes_drawer_delete_selected')
    qa.wait("bool(drv.find(popup=True, text='Delete'))")
    qa.click(popup=True, text='Delete')
    qa.wait(f'len({WM}.mixar_scene_tabs)==1')
    qa.wait("bool(drv.find(surface='scenes_drawer_new'))")
    qa.step('all_thirteen_deleted_with_valid_replacement', qa.eval,
            "assert not drv.find(surface='scenes_drawer_delete_selected')\n"
            f"assert {WM}.mixar_scene_tabs[0].scene_name==drv.main_window().scene.name\nresult=True")
    capture(qa, out / 'replacement.png')
    return {'rapid_add': True, 'scroll_stable': True, 'delete_offscreen': True,
            'screenshots': str(out)}


if __name__ == '__main__':
    run_scenario('scenes_panel_stability_e2e', run)
