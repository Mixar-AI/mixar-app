#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit pin: the Moodboard node pie opens on Ctrl+Tab, never on backtick.

Standalone MIXIE editor host with the pointer in the canvas:
  1. ACCENT_GRAVE must open NO popup (the key belongs to the Zen drawer toggle);
  2. Ctrl+Tab must open the node pie (same template widgets as the + Add menu).

Run with QA_HARNESS and MIXAR_QA_PORT against an isolated Dev QA app:
    QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
        QA_SCENARIO_OUT=/tmp/moodboard-pie-key python3 tests/qa/moodboard_pie_key_e2e.py
Inspect the emitted PNGs; the state asserts alone do not prove the pixels.
"""

import os
from pathlib import Path
import time

from moodboard_catalog_templates_e2e import ADD, capability, fixture, run_scenario
from lib import ScenarioFail  # noqa: E402  (sys.path set by the import above)

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-pie-key'))
CANVAS = '''
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'MIXIE')
region = next(r for r in area.regions if r.type == 'WINDOW')
result = [region.x, region.y, region.x + region.width, region.y + region.height]
'''


def require(condition, message):
    if not condition:
        raise ScenarioFail(message)


def point_into_canvas(qa):
    x0, y0, x1, y1 = qa.eval(CANVAS)
    x, y = (x0 + x1) // 2, (y0 + y1) // 2
    qa.eval('import qa_driver as d\n'
            f'd.move_to(drv.main_window(), {x}, {y})\n'
            'result = 1')
    return {'x': x, 'y': y}


def popups(qa):
    return [w for w in qa.find()['widgets'] if w.get('popup')]


def pie_widgets(qa):
    return qa.find(op=ADD, popup=True)['widgets']


def backtick_opens_nothing(qa):
    point_into_canvas(qa)
    qa.press('ACCENT_GRAVE')
    # A pie that IS bound needs one main-loop cycle to appear; keep looking
    # for a full second so a slow popup cannot slip past the assertion.
    deadline = time.monotonic() + 1.0
    while True:
        require(not pie_widgets(qa), 'Backtick opened the node pie')
        require(not popups(qa), f'Backtick opened a popup: {popups(qa)}')
        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)
    qa.snap(str(OUT / '01_backtick_no_pie.png'))
    return True


def ctrl_tab_opens_pie(qa):
    point_into_canvas(qa)
    qa.press('TAB', ctrl=True)
    qa.wait(f"len(drv.find(popup=True, op={ADD!r})) >= 1", timeout=4)
    widgets = pie_widgets(qa)
    labels = {w['text'] for w in widgets}
    require('Add Mesh' in labels, f'Pie lacks the shared Add entries: {widgets}')
    require(all(w['enabled'] for w in widgets), widgets)
    qa.snap(str(OUT / '02_ctrl_tab_pie.png'))
    qa.press('ESC')
    qa.wait("not any(w.get('popup') for w in drv.find())", timeout=4)
    return sorted(labels)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.dismiss_splash()
    qa.wait("__import__('mixar.bootstrap.generation_catalog_cache',fromlist=['is_loaded']).is_loaded()",
            timeout=30)
    qa.eval('''
assert __import__('os').environ.get('MIXAR_QA') == '1'
from mixar.bootstrap import generation_catalog_cache as catalog
bpy.app.driver_namespace['_qa_pie_key_catalog'] = catalog._catalog
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type in {'VIEW_3D','MIXIE'})
area.type='MIXIE'
ui=next((r for r in area.regions if r.type=='UI'),None)
if ui is not None and ui.width>1:
    with bpy.context.temp_override(window=win,area=area,region=ui):
        bpy.ops.screen.region_toggle(region_type='UI')
result=True
''')
    try:
        fixture(qa, [capability('image_gen', 'image_gen'),
                     capability('model_gen', 'image_to_3d')])
        qa.step('backtick_opens_nothing', backtick_opens_nothing, qa)
        labels = qa.step('ctrl_tab_opens_pie', ctrl_tab_opens_pie, qa)
        require(len(labels) >= 2, labels)
        return {'credits': 0, 'screenshots': str(OUT), 'pie_entries': labels}
    finally:
        qa.eval('''
from mixar.bootstrap import generation_catalog_cache as catalog
with catalog._lock:
    catalog._catalog=bpy.app.driver_namespace.pop('_qa_pie_key_catalog')
    catalog._bump_enum_version_locked()
catalog._on_catalog_swapped()
result=True
''')


if __name__ == '__main__':
    run_scenario('moodboard_pie_key', run)
