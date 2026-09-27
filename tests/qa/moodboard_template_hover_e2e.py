#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit template hover replay in an isolated QA app; inspect saved PNGs.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT as for the Forest replay.
"""

import os
from pathlib import Path
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-template-hover'))
BLOCK = 'MIXIE_PT_canvas_templates'


def capture(qa, query, name):
    path = OUT / f'{name}.png'
    for _ in range(2):
        qa.cmd('snap', path=str(path), target=query, margin=0)
        time.sleep(.25)
    with Image.open(path).convert('RGB') as image:
        hits = sum(n for n, c in image.getcolors(image.width * image.height)
                   if all(abs(a-b) <= 1 for a, b in zip(c, (47, 89, 47))))
        return hits / (image.width * image.height)


def check_host(qa, host):
    region = 'TOOL_PROPS' if host == 'VIEW_3D' else 'WINDOW'
    widgets = qa.eval(f"result=[w for w in drv.find(area_type={host!r}, "
                      f"region_type={region!r}) if w.get('block')=={BLOCK!r}]")
    assert len(widgets) >= 2, widgets
    for index, widget in enumerate(widgets):
        if not widget.get('enabled', True):
            continue
        query = dict(area_type=host, region_type=region,
                     text=widget.get('text') or widget['tip'], but_type=widget['type'])
        qa.eval(f"w=drv.find_one(**{query!r}); x0,y0,x1,y1=w['rect']; "
                "drv.move_to(drv.main_window(),int((x0+x1)/2),int((y0+y1)/2)); result=True")
        qa.wait(f"drv.find_one(**{query!r})['mixar_motion']['hover'] > .99", timeout=5)
        assert capture(qa, query, f'{host}-{index}-hover') > .3, query
        qa.eval(f"w=drv.find_one(**{query!r}); x0,y0,x1,y1=w['rect']; "
                "drv.move_to(drv.main_window(),int((x0+x1)/2),int(y0-120)); result=True")
        qa.wait(f"drv.find_one(**{query!r})['mixar_motion']['hover'] < .01", timeout=5)
        assert capture(qa, query, f'{host}-{index}-idle') < .02, query
    return len(widgets)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval("""
import os
assert os.environ.get('MIXAR_QA') == '1'
from mixar.modules.onboarding.core.tour import session
if session.current(): session.current().stop('hover-qa')
bpy.context.preferences.view.show_tooltips=False
bpy.ops.mixar.apply_forest_theme()
drv.main_window().workspace=bpy.data.workspaces['Zen Mode']
result=True
""")
    qa.wait("bool(drv.find(surface='moodboard_drawer_grip'))", timeout=15)
    qa.click(surface='moodboard_drawer_grip')
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .99', timeout=10)
    drawer = qa.step('drawer', check_host, qa, 'VIEW_3D')
    qa.click(surface='moodboard_drawer_grip')
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount < .01', timeout=10)
    qa.eval("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').type='MIXIE'; result=True")
    qa.wait("bool(drv.find(area_type='MIXIE', op='MIXIE_OT_moodboard_add_template'))", timeout=10)
    editor = qa.step('editor', check_host, qa, 'MIXIE')
    return {'drawer_buttons': drawer, 'editor_buttons': editor, 'hover': '#2F592F'}


if __name__ == '__main__':
    run_scenario('moodboard_template_hover', run)
