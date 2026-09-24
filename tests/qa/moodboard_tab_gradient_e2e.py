#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit reference-gradient replay; requires an isolated QA app.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4893 \
QA_SCENARIO_OUT=/tmp/moodboard-tab python3 tests/qa/moodboard_tab_gradient_e2e.py
"""
import json
import os
from pathlib import Path
from statistics import median
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from zen_scene_toolbar_e2e import reset_zen_scene

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-tab'))


def capture(qa, name):
    path = OUT / f'{name}.png'
    qa.cmd('snap', path=str(path), target={'surface': 'moodboard_drawer_grip'}, margin=0)
    with Image.open(path).convert('RGB') as img:
        w, h = img.size
        # Stay outside the vertical text and the rounded ends.
        left = [median(img.getpixel((w // 5, y))[c] for y in range(h // 5, 4 * h // 5))
                for c in range(3)]
        right = [median(img.getpixel((4 * w // 5, y))[c] for y in range(h // 5, 4 * h // 5))
                 for c in range(3)]
        assert left[1] > left[0] * 1.35, left
        assert right[1] < left[1] * .55, (left, right)
        top = img.getpixel((w // 5, h // 5))
        bottom = img.getpixel((w // 5, 4 * h // 5))
        assert max(abs(a-b) for a, b in zip(top, bottom)) <= 3, (top, bottom)
    return {'left': left, 'right': right, 'size': [w, h]}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    reset_zen_scene(qa)
    saved = qa.eval('result=bpy.context.preferences.view.ui_scale')
    checks = {}
    try:
        for scale in (1.0, 1.5):
            qa.eval(f'bpy.context.preferences.view.ui_scale={saved * scale}; result=True')
            qa.wait("bool(drv.find(surface='moodboard_drawer_grip'))", timeout=6)
            checks[f'closed-{scale}'] = qa.step(f'closed-{scale}', capture, qa, f'closed-{scale}')
            qa.click(surface='moodboard_drawer_grip')
            qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .99', timeout=5)
            checks[f'open-{scale}'] = qa.step(f'open-{scale}', capture, qa, f'open-{scale}')
            qa.cmd('snap', path=str(OUT / f'drawer-{scale}.png'), area='VIEW_3D')
            qa.click(surface='moodboard_drawer_grip')
            qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount < .01', timeout=5)
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved}; result=True')
    verdict = {'checks': checks, 'paid_requests': 0}
    (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2)+'\n')
    return verdict


if __name__ == '__main__':
    run_scenario('moodboard_tab_gradient_e2e', run)
