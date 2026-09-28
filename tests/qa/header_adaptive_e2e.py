#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Adaptive Add Objects menu and overflow at five UI scales; no paid requests.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT against an isolated
Dev app. Review every emitted header capture as well as the geometry verdict.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/header-adaptive'))
HEADER = {'area_type': 'VIEW_3D', 'region_type': 'HEADER'}


def redraw(qa, scale):
    qa.eval(f'''
def update():
    bpy.context.preferences.view.ui_scale = {scale!r}
    for area in drv.main_window().screen.areas:
        area.tag_redraw()
    yield .5
    return True
result = update()
''')


def check(qa, scale):
    redraw(qa, scale)
    bounds = qa.eval('''
a = next(a for a in drv.main_window().screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'HEADER')
result = {'rect': [r.x, r.y, r.x+r.width, r.y+r.height],
          'scale': bpy.context.preferences.system.ui_scale}
''')
    target = qa.find(text='Add Objects', **HEADER)['widgets']
    assert len(target) == 1, target
    assert qa.find(op='MIXAR_OT_director_enter', **HEADER)['total'] == 1
    x0, y0, x1, y1 = target[0]['rect']
    rx0, ry0, rx1, ry1 = bounds['rect']
    assert rx0 <= x0 < x1 <= rx1 and ry0 <= y0 < y1 <= ry1, (target, bounds)
    assert (x1-x0)/bounds['scale'] >= 110, (target, bounds)
    for widget in qa.find(**HEADER)['widgets']:
        if widget['type'] != 'Other':
            assert rx0 <= widget['rect'][0] < widget['rect'][2] <= rx1, (widget, bounds)
    qa.cmd('snap', path=str(OUT / f'header-{scale}.png'), area='VIEW_3D', region='HEADER')
    qa.click(text='Add Objects', **HEADER)
    qa.wait("bool(drv.find(text='Mesh', popup=True))", timeout=5)
    qa.cmd('snap', path=str(OUT / f'add-menu-{scale}.png'))
    qa.press('ESC')
    logical_width = (rx1-rx0)/bounds['scale']
    if logical_width < 1180:
        # The three native popovers are render, shading, then overflow.
        qa.eval("""
def open_overflow():
    targets = drv.find(area_type='VIEW_3D', region_type='HEADER', but_type='Popover')
    assert len(targets) == 3, targets
    yield from drv.click_steps(targets[-1])
    yield .2
    return True
result = open_overflow()
""")
        qa.wait("bool(drv.find(text='Sky Light', popup=True))", timeout=5)
        assert qa.find(text='Export', popup=True)['total']
        qa.cmd('snap', path=str(OUT / f'overflow-{scale}.png'))
        qa.press('ESC')
    return {'logical_width': logical_width, 'add_rect': target[0]['rect']}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    saved = qa.eval('''
import os
assert os.environ.get('MIXAR_QA') == '1'
result = {'scale': bpy.context.preferences.view.ui_scale,
          'zen': drv.main_window().workspace.name == 'Zen Mode'}
''')
    qa.cmd('dismiss_splash')
    if not saved['zen']:
        qa.click(op='MIXAR_OT_set_ui_mode_ai')
    qa.wait("drv.main_window().workspace.name == 'Zen Mode'", timeout=10)
    try:
        return {'layouts': {str(s): qa.step(str(s), check, qa, s)
                            for s in (.8, 1., 1.25, 1.5, 2.)}, 'backend_calls': 0}
    finally:
        redraw(qa, saved['scale'])
        if not saved['zen']:
            qa.click(op='MIXAR_OT_set_ui_mode_pro')


if __name__ == '__main__':
    run_scenario('header_adaptive_e2e', run)
