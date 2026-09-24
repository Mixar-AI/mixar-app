#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit top menu height, sample labels and Cinema gradient replay.

Use QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT with an isolated QA app.
"""
import json
import os
from pathlib import Path
from statistics import median
import sys
from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from zen_scene_toolbar_e2e import reset_zen_scene, HEADER, SETUP
from zen_toolbar_controls_e2e import settings_query, dismiss

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/topbar-chrome'))


def gradient(qa, name):
    path = OUT / f'{name}.png'
    qa.cmd('snap', path=str(path), target={**HEADER, 'text': 'Cinema Mode'}, margin=0)
    with Image.open(path).convert('RGB') as img:
        w, h = img.size
        top = [median(img.getpixel((x, h // 5))[c] for x in range(w // 4, 3*w // 4)) for c in range(3)]
        bottom = [median(img.getpixel((x, 4*h // 5))[c] for x in range(w // 4, 3*w // 4)) for c in range(3)]
    assert top[1] > top[0] * 1.3 and top[1] > bottom[1] + 8, (top, bottom)
    return {'top': top, 'bottom': bottom}


def layout(qa, suffix):
    path = OUT / f'full-{suffix}.png'
    qa.cmd('snap', path=str(path))
    with Image.open(path) as img:
        height = img.height
    area_top, scale = qa.eval(SETUP + 'result=[area.y+area.height, bpy.context.preferences.system.ui_scale]')
    logical_height = (height - area_top) / scale
    assert abs(logical_height - 36) <= 2, logical_height
    qa.click(area_type='TOPBAR', text='File', but_type='Pulldown')
    assert qa.find(popup=True)['widgets'], 'File menu did not open'
    qa.press('ESC')
    query = settings_query(qa)
    qa.cmd('choose', widget={**query, 'prop':'mixar_zen_sample_target'}, item='Viewport Samples')
    label = qa.find(**query, prop='mixar_zen_sample_target')['widgets'][0]
    assert label['text'].casefold() == 'viewport samples', label
    qa.cmd('snap', path=str(OUT / f'samples-{suffix}.png'))
    qa.cmd('choose', widget={**query, 'prop':'mixar_zen_sample_target'}, item='Render Samples')
    dismiss(qa, query)
    return {'height':logical_height, 'sample_label':label['text']}


def account(qa, suffix):
    saved = qa.eval('result=[bpy.context.window_manager.mixie_chat_is_logged_in, '
                    'drv.main_window().scene.mixie_chat_user_id]')
    sizes = {}
    try:
        for logged_in, label in ((False, 'Login'), (True, 'qa@example.invalid')):
            # UI-only fixture in the offline app: no credentials or login request.
            qa.eval(f'bpy.context.window_manager.mixie_chat_is_logged_in={logged_in}; '
                    f'drv.main_window().scene.mixie_chat_user_id={label!r}; '
                    '[a.tag_redraw() for a in drv.main_window().global_areas]; result=True')
            query = {'area_type': 'TOPBAR', 'text': label}
            qa.wait(f'bool(drv.find(**{query!r}))', timeout=5)
            rect = qa.find(**query)['widgets'][0]['rect']
            scale = qa.eval('result=bpy.context.preferences.system.ui_scale')
            height = (rect[3] - rect[1]) / scale
            assert 30 <= height <= 33, (label, height)
            region_y, region_height = qa.eval(
                "result=next((r.y, r.height) for a in drv.main_window().global_areas "
                "if a.type == 'TOPBAR' for r in a.regions if r.alignment == 'RIGHT')")
            assert abs((rect[1] + rect[3]) / 2 - region_y - region_height / 2) <= 1
            name = 'profile' if logged_in else 'login'
            path = OUT / f'{name}-{suffix}.png'
            qa.cmd('snap', path=str(path), target=query, margin=0)
            if not logged_in:
                with Image.open(path).convert('RGB') as img:
                    columns = [x for y in range(img.height) for x in range(img.width)
                               if min(img.getpixel((x, y))) > 130]
                    assert columns, 'Login content missing'
                    padding = min(min(columns), img.width - 1 - max(columns)) / scale
                    assert padding >= 8, padding
            qa.click(**query)
            assert qa.find(popup=True)['widgets'], f'{name} popover did not open'
            qa.press('ESC')
            sizes[name] = height
    finally:
        qa.eval(f'bpy.context.window_manager.mixie_chat_is_logged_in={saved[0]!r}; '
                f'drv.main_window().scene.mixie_chat_user_id={saved[1]!r}; '
                '[a.tag_redraw() for a in drv.main_window().global_areas]; result=True')
    return sizes


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    reset_zen_scene(qa)
    saved = qa.eval('result=bpy.context.preferences.view.ui_scale')
    checks = {}
    try:
        for factor in (1, 1.5):
            qa.eval(f'bpy.context.preferences.view.ui_scale={saved * factor}; result=True')
            checks[f'layout-{factor}'] = qa.step(f'layout-{factor}', layout, qa, str(factor))
            checks[f'account-{factor}'] = qa.step(f'account-{factor}', account, qa, str(factor))
            checks[f'gradient-{factor}'] = qa.step(f'gradient-{factor}', gradient, qa, f'cinema-{factor}')
        qa.click(**HEADER, op='MIXAR_OT_director_enter')
        qa.wait('drv.main_window().scene.mixar_director.is_directing', timeout=8)
        checks['active-gradient'] = qa.step('active-gradient', gradient, qa, 'cinema-active')
        qa.click(**HEADER, op='MIXAR_OT_director_finish')
        qa.wait('not drv.main_window().scene.mixar_director.is_directing', timeout=8)
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved}; result=True')
    result = {'checks':checks, 'paid_requests':0}
    (OUT / 'verdict.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__ == '__main__':
    run_scenario('topbar_chrome_e2e', run)
