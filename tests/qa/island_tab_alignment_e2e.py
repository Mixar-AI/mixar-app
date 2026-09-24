#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit check of the island's left navigation and right utility tabs.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT on an isolated Dev app.
Uses native button bounds for assertions, clicks and screenshots.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

TABS = {
    'AGENT': 'Agent chat',
    'THREE_D': '3D generation',
    'IMAGE': 'Image generation',
    'VIDEO': 'Video generation',
    'SPLAT': 'Gaussian Splat world generation',
    'GENERATIONS': 'Your generations and connected asset libraries',
    'QUEUE': 'Generation queue',
}
AGENT = {'area_type': 'AGENT_BUBBLE', 'text': TABS['AGENT']}


def assert_tab_alignment(qa):
    pills = [qa.find(area_type='AGENT_BUBBLE', text=tip)['widgets'][0]['rect']
             for tip in TABS.values()]
    area = qa.eval(f'h=drv.find_one(**{AGENT!r}); '
                   'a=h["_area"]; result=[a.x,a.width]')
    x, width = area
    left, right = pills[0][0] - x, x + width - pills[-1][2]
    assert 0 <= left <= width * .015 and 0 <= right <= width * .015, (area, pills)
    assert abs(left - right) <= 2, (left, right)
    gaps = [b[0] - a[2] for a, b in zip(pills, pills[1:])]
    assert min(gaps) > 0, pills
    compact = gaps[:4] + gaps[5:]
    assert max(compact) <= width * .01, gaps
    assert gaps[4] >= max(compact) - 2, gaps
    assert max(p[1] for p in pills) - min(p[1] for p in pills) <= 2, pills
    return {'width': width, 'outer_margins': [left, right], 'gaps': gaps}


def capture_strip(qa, out, name):
    return qa.cmd('snap', path=str(out / f'{name}.png'),
                  target=AGENT, margin=3000)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/island-tab-alignment'))
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.context.window_manager, 'mixar_bubble_tab')", timeout=30)
    saved_scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    saved_tab = qa.eval('result=bpy.context.window_manager.mixar_bubble_tab')
    qa.eval('result=str(bpy.ops.mixar.agent_bubble_show_window())')
    qa.wait(f'bool(drv.find(**{AGENT!r}))', timeout=5)
    saved_size = qa.eval(f'w=drv.find_one(**{AGENT!r})["_win"]; '
                         'result=[w.width,w.height]')
    metrics = {}
    try:
        qa.click(**AGENT)
        for scale in (1.0, 1.25):
            qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
            for width in (560, 678, 1100):
                qa.eval(f'w=drv.find_one(**{AGENT!r})["_win"]\n'
                        'with bpy.context.temp_override(window=w):\n'
                        f'    bpy.ops.mixar.bubble_set_size(width={width},height=407)\n'
                        'result=True')
                time.sleep(.5)
                name = f'groups-{width}-{scale}'
                metrics[name] = qa.step(name, assert_tab_alignment, qa)
                capture_strip(qa, out, name)
        for key, tip in TABS.items():
            qa.click(area_type='AGENT_BUBBLE', text=tip)
            qa.wait(f'bpy.context.window_manager.mixar_bubble_tab=={key!r}', timeout=5)
            qa.step(f'click-{key.lower()}', assert_tab_alignment, qa)
        return {'geometry': metrics, 'backend_calls': 0, 'screenshots': str(out)}
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved_scale}; '
                f'bpy.context.window_manager.mixar_bubble_tab={saved_tab!r}; result=True')
        qa.eval(f'w=drv.find_one(**{AGENT!r})["_win"]\n'
                'with bpy.context.temp_override(window=w):\n'
                f'    bpy.ops.mixar.bubble_set_size(width={saved_size[0]},height={saved_size[1]})\n'
                'result=True')


if __name__ == '__main__':
    run_scenario('island_tab_alignment_e2e', run)
