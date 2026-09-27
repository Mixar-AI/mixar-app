#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Scenes hamburger panel: no-credit native layout and drag replay.

Run startup_health first in a fresh isolated QA app, then:
QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4796 \\
  python3 tests/qa/scenes_panel_e2e.py

Asserts add placement, insets, click vs drag, both reorder directions, cancel,
edge scrolling and scene identity. Read the saved screenshots for visual QA.
"""
import inspect
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

WM = 'bpy.context.window_manager'


def begin_drag(source, target, direction):
    """Injected into the app: all coordinates come from live semantic targets."""
    win = drv.main_window()
    card = drv.find_one(surface='scenes_drawer_card', text=source)
    dest = drv.find_one(surface='scenes_drawer_card', text=target)
    x, y = drv.pick_click_point(card)
    rect = dest['rect']
    # Above/below the destination's centre selects the insertion side.
    end_y = int(rect[1] + (rect[3] - rect[1]) * (.85 if direction == 'up' else .15))
    drv.move_to(win, x, y)
    yield .08
    drv._sim(win, type='LEFTMOUSE', value='PRESS', x=x, y=y)
    yield .08
    for step in range(1, 13):
        drv.move_to(win, x, y + (end_y - y) * step // 12)
        yield .025
    return True


def finish_drag(cancel=False, outside=False):
    win = drv.main_window()
    if cancel:
        drv._sim(win, type='ESC', value='PRESS')
        yield .05
        drv._sim(win, type='ESC', value='RELEASE')
    if outside:
        panel = drv.find_one(surface='scenes_drawer_panel')['rect']
        drv.move_to(win, panel[2] + 20, (panel[1] + panel[3]) // 2)
        yield .05
    drv._sim(win, type='LEFTMOUSE', value='RELEASE')
    yield .25
    return True


def resize_panel():
    win = drv.main_window()
    edge = drv.find_one(surface='scenes_drawer_edge')
    x, y = drv.pick_click_point(edge)
    width = edge['rect'][2] - drv.find_one(surface='scenes_drawer_panel')['rect'][0]
    drv.move_to(win, x, y)
    yield .08
    drv._sim(win, type='LEFTMOUSE', value='PRESS', x=x, y=y)
    yield .08
    for step in range(1, 9):
        drv.move_to(win, x + int(width * .25 * step / 8), y)
        yield .025
    return True


def geometry():
    panel = drv.find_one(surface='scenes_drawer_panel')['rect']
    cards = drv.find(surface='scenes_drawer_card')
    new = drv.find_one(surface='scenes_drawer_new')['rect']
    region = next(r for a in drv.main_window().screen.areas if a.type == 'VIEW_3D'
                  for r in a.regions if r.type == 'NAVIGATION_BAR')
    assert panel[1] > region.y and panel[3] < region.y + region.height, (panel, region.y)
    assert new[1] > max(card['rect'][3] for card in cards), (new, cards)
    assert panel[1] < new[1] < new[3] < panel[3]
    assert new[2] - new[0] > 3 * (new[3] - new[1]), new
    return {'panel': panel, 'new': new, 'cards': [c['rect'] for c in cards]}


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/scenes-panel-qa')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA') == '1'\nresult=True")
    qa.dismiss_splash()
    qa.wait(f"hasattr({WM}, 'mixar_scene_tabs')", timeout=30)
    # Each harness eval has a fresh namespace; include helpers in every request.
    helpers = '\n'.join(inspect.getsource(fn) for fn in (begin_drag, finish_drag, resize_panel, geometry))
    native_eval = qa.eval
    qa.eval = lambda code: native_eval(helpers + '\n' + code)
    qa.eval(f"assert len({WM}.mixar_scene_tabs)==1, 'Use a fresh isolated QA profile'\nresult=True")
    if qa.eval(f'result={WM}.mixar_scenes_drawer_amount') < .98:
        qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
    qa.wait(f'{WM}.mixar_scenes_drawer_amount >= .98')
    qa.step('one_scene_layout', qa.eval, 'result=geometry()')
    qa.snap(str(out / 'one-scene.png'))
    for count in (2, 3):
        qa.click(surface='scenes_drawer_new')
        qa.wait(f'len({WM}.mixar_scene_tabs)=={count}')
    names = qa.eval(f'result=[t.scene_name for t in {WM}.mixar_scene_tabs]')
    qa.step('three_scene_layout', qa.eval, 'result=geometry()')
    qa.snap(str(out / 'three-scenes.png'))
    # The wash follows selection without changing any card hit geometry.
    original_rects = qa.eval("result={c['text']: c['rect'] for c in drv.find(surface='scenes_drawer_card')}")
    for index, name in enumerate(names):
        qa.click(surface='scenes_drawer_card', text=name)
        qa.wait(f"drv.main_window().scene.name=={name!r} and "
                f"drv.find_one(surface='scenes_drawer_card', text={name!r})['sel']")
        qa.step(f'selection_{index}_geometry', qa.eval,
                "cards=drv.find(surface='scenes_drawer_card')\n"
                f"assert [c['text'] for c in cards if c.get('sel', False)]==[{name!r}]\n"
                f"assert {{c['text']:c['rect'] for c in cards}}=={original_rects!r}\n"
                "result=True")
        qa.snap(str(out / f'selected-{index}.png'))
        if index == 1:
            qa.cmd('snap', path=str(out / 'selected-detail.png'),
                   target={'surface': 'scenes_drawer_card', 'text': name}, margin=180)
    qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
    qa.wait(f'{WM}.mixar_scenes_drawer_amount <= .01')
    qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
    qa.wait(f'{WM}.mixar_scenes_drawer_amount >= .98')
    qa.wait(f"drv.find_one(surface='scenes_drawer_card', text={names[-1]!r})['sel']")
    original_width = qa.eval(f'result={WM}.mixar_scenes_drawer_width')
    qa.eval('result=resize_panel()')
    qa.step('selection_resize', qa.eval,
            f'assert {WM}.mixar_scenes_drawer_width > {original_width!r}\n'
            f"assert drv.find_one(surface='scenes_drawer_card', text={names[-1]!r})['sel']\n"
            'result=geometry()')
    qa.snap(str(out / 'selected-resized.png'))
    qa.eval('result=finish_drag(cancel=True)')
    qa.wait(f'abs({WM}.mixar_scenes_drawer_width - {original_width!r}) < .1')
    active = qa.eval('result=drv.main_window().scene.name')

    before = qa.eval("result={c['text']: c['rect'][3] for c in drv.find(surface='scenes_drawer_card')}")
    qa.eval(f'result=begin_drag({names[0]!r}, {names[2]!r}, "down")')
    qa.wait("bool(drv.find(surface='scenes_drawer_drag'))")
    qa.step('drag_feedback', qa.eval,
            f"assert drv.find_one(surface='scenes_drawer_drag')['text']=={names[0]!r}\n"
            "assert drv.find(surface='scenes_drawer_drop')\nresult=True")
    qa.step('neighbors_slide_into_gap', qa.eval,
            f"assert drv.find_one(surface='scenes_drawer_card', text={names[1]!r})['rect'][3] > {before[names[1]]}\n"
            f"assert not drv.find(surface='scenes_drawer_card', text={names[0]!r})\nresult=True")
    qa.snap(str(out / 'dragging-down.png'))
    qa.eval('result=finish_drag()')
    expected = names[1:] + names[:1]
    qa.wait(f'[t.scene_name for t in {WM}.mixar_scene_tabs]=={expected!r}')
    qa.step('reorder_keeps_active_scene', qa.eval,
            f'assert drv.main_window().scene.name=={active!r}\nresult=True')
    qa.eval(f'result=begin_drag({names[0]!r}, {names[1]!r}, "up")')
    qa.snap(str(out / 'dragging-up.png'))
    qa.eval('result=finish_drag()')
    qa.wait(f'[t.scene_name for t in {WM}.mixar_scene_tabs]=={names!r}')
    for mode in ('cancel=True', 'outside=True'):
        qa.eval(f'result=begin_drag({names[0]!r}, {names[2]!r}, "down")')
        qa.eval(f'result=finish_drag({mode})')
        qa.step(mode, qa.eval, f'assert [t.scene_name for t in {WM}.mixar_scene_tabs]=={names!r}\n'
                "assert not drv.find(surface='scenes_drawer_drag')\nresult=True")
    qa.click(surface='scenes_drawer_card', text=names[0])
    qa.wait(f'drv.main_window().scene.name=={names[0]!r}')

    # Fill the list through the actual add button; it must stay reachable.
    for count in range(4, 17):
        qa.click(surface='scenes_drawer_new')
        qa.wait(f'len({WM}.mixar_scene_tabs)=={count}')
    qa.step('overflow_add_stays_in_header', qa.eval, 'result=geometry()')
    qa.snap(str(out / 'overflow.png'))
    last = qa.eval(f'result={WM}.mixar_scene_tabs[-1].scene_name')
    qa.eval(f'''
def scroll_drag():
    win=drv.main_window()
    source=drv.find_one(surface='scenes_drawer_card', text={names[0]!r})
    x,y=drv.pick_click_point(source)
    panel=drv.find_one(surface='scenes_drawer_panel')['rect']
    drv.move_to(win,x,y)
    yield .08
    drv._sim(win,type='LEFTMOUSE',value='PRESS',x=x,y=y)
    yield .08
    drv.move_to(win,x,panel[1]+2)
    yield 3.5
    return True
result=scroll_drag()
''')
    qa.wait(f"any(c['text']=={last!r} for c in drv.find(surface='scenes_drawer_card'))", timeout=10)
    qa.snap(str(out / 'edge-auto-scroll.png'))
    qa.eval('result=finish_drag()')
    qa.wait(f'{WM}.mixar_scene_tabs[-1].scene_name=={names[0]!r}')
    qa.snap(str(out / 'reordered.png'))
    return {'original_order': names, 'both_directions': True, 'cancel': True,
            'outside_drop': True, 'overflow_auto_scroll': True, 'screenshots': str(out)}


if __name__ == '__main__':
    run_scenario('scenes_panel_e2e', run)
