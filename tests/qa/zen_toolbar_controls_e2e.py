#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit toolbar regression replay against an isolated real QA app.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4893 \
QA_SCENARIO_OUT=/tmp/zen-toolbar-controls python3 tests/qa/zen_toolbar_controls_e2e.py
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from zen_scene_toolbar_e2e import HEADER, SETUP, reset_zen_scene

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/zen-toolbar-controls'))


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / (name + '.png')), area='VIEW_3D')


def settings_query(qa):
    if qa.find(**HEADER, prop='engine')['widgets']:
        return HEADER
    qa.click(**HEADER, text='Render Settings')
    return {'popup': True}


def dismiss(qa, query):
    if query.get('popup'):
        qa.press('ESC')


def grid(qa):
    initial = qa.eval(SETUP + "result=[view.overlay.show_floor, view.overlay.show_axis_x, view.overlay.show_axis_y, view.overlay.show_relationship_lines]")
    qa.click(**HEADER, op='MIXAR_OT_zen_toggle_guides')
    hidden = qa.eval(SETUP + "result=[view.overlay.show_floor, view.overlay.show_axis_x, view.overlay.show_axis_y, view.overlay.show_relationship_lines]")
    assert hidden == [False] * 4, hidden
    snap(qa, 'grid-hidden')
    qa.click(**HEADER, op='MIXAR_OT_zen_toggle_guides')
    restored = qa.eval(SETUP + "result=[view.overlay.show_floor, view.overlay.show_axis_x, view.overlay.show_axis_y, view.overlay.show_relationship_lines]")
    assert restored == [True] * 4, restored
    return {'hidden': hidden, 'restored': restored}


def samples(qa):
    results = {}
    for label, engine, owner, render, viewport in (
        ('Cycles', 'CYCLES', 'cycles', 'samples', 'preview_samples'),
        ('EEVEE', 'BLENDER_EEVEE', 'eevee', 'taa_render_samples', 'taa_samples'),
        ('Workbench', 'BLENDER_WORKBENCH', 'display', 'render_aa', 'viewport_aa'),
    ):
        query = settings_query(qa)
        qa.cmd('choose', widget={**query, 'prop': 'engine'}, item=label)
        qa.wait(f"drv.main_window().scene.render.engine == {engine!r}", timeout=5)
        qa.cmd('choose', widget={**query, 'prop': 'mixar_zen_sample_target'}, item='Render Samples')
        if engine == 'BLENDER_WORKBENCH':
            qa.cmd('choose', widget={**query, 'prop': render}, item='32 Samples')
        else:
            qa.cmd('set_text', widget={**query, 'prop': render}, text='96')
        saved = qa.eval(SETUP + f'result=scene.{owner}.{render}')
        qa.cmd('choose', widget={**query, 'prop': 'mixar_zen_sample_target'}, item='Viewport Samples')
        if engine == 'BLENDER_WORKBENCH':
            qa.cmd('choose', widget={**query, 'prop': viewport}, item='16 Samples')
            expected = '16'
        else:
            qa.cmd('set_text', widget={**query, 'prop': viewport}, text='24')
            qa.cmd('set_text', widget={**query, 'prop': viewport}, text='999', enter=False)
            qa.press('ESC')
            expected = 24
        assert qa.eval(SETUP + f'result=scene.{owner}.{viewport}') == expected
        assert qa.eval(SETUP + f'result=scene.{owner}.{render}') == saved
        snap(qa, 'viewport-samples-' + engine.lower())
        qa.cmd('choose', widget={**query, 'prop': 'mixar_zen_sample_target'}, item='Render Samples')
        assert qa.eval(SETUP + f'result=scene.{owner}.{render}') == saved
        dismiss(qa, query)
        results[engine] = {'render': saved, 'viewport': expected}
    query = settings_query(qa)
    qa.cmd('choose', widget={**query, 'prop': 'engine'}, item='EEVEE')
    dismiss(qa, query)
    return results


def cinema(qa):
    assert not qa.find(area_type='TOPBAR', op='MIXAR_OT_director_enter')['widgets']
    button = qa.find(**HEADER, op='MIXAR_OT_director_enter')['widgets'][0]['rect']
    playback = sorted(qa.find(**HEADER, op='SCREEN_OT_keyframe_jump')['widgets'],
                      key=lambda w: w['rect'][0])[0]['rect']
    scale = qa.eval('result=bpy.context.preferences.system.ui_scale')
    assert abs(button[1] - playback[1]) <= 1, (button, playback)
    assert abs(button[3] - playback[3]) <= 1, (button, playback)
    assert 0 < (playback[0] - button[2]) / scale <= 16, (button, playback)
    qa.click(**HEADER, op='MIXAR_OT_director_enter')
    qa.wait('drv.main_window().scene.mixar_director.is_directing', timeout=8)
    snap(qa, 'cinema-active')
    qa.click(**HEADER, op='MIXAR_OT_director_finish')
    qa.wait('not drv.main_window().scene.mixar_director.is_directing', timeout=8)
    return {'entered': True, 'exited': True}


def sky_and_drawer(qa):
    query = HEADER
    if not qa.find(**HEADER, op='MIXAR_OT_zen_set_sky')['widgets']:
        qa.click(**HEADER, text='Sky Light')
        query = {'popup': True}
    buttons = qa.find(**query, op='MIXAR_OT_zen_set_sky')['widgets']
    scale = qa.eval('result=bpy.context.preferences.system.ui_scale')
    assert all((w['rect'][2] - w['rect'][0]) / scale >= 38 for w in buttons), buttons
    original = qa.eval(SETUP + 'result=scene.world.name if scene.world else None')
    qa.click(**query, op='MIXAR_OT_zen_set_sky', text='ON')
    assert qa.eval(SETUP + 'result=scene.world == scene.mixar_zen_sky.sky_world')
    snap(qa, 'sky-on')
    qa.click(**query, op='MIXAR_OT_zen_set_sky', text='OFF')
    assert qa.eval(SETUP + 'result=scene.world.name if scene.world else None') == original
    dismiss(qa, query)
    qa.click(surface='moodboard_drawer_grip')
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .99', timeout=5)
    snap(qa, 'moodboard-open')
    qa.click(surface='moodboard_drawer_grip')
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount < .01', timeout=5)
    snap(qa, 'toolbar-final')
    return {'sky_restored': True, 'drawer_open_close': True}


def compact(qa):
    saved = qa.eval('result=bpy.context.preferences.view.ui_scale')
    try:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved * 1.5}; result=True')
        qa.wait(f"bool(drv.find(text='Render Settings', **{HEADER!r}))", timeout=6)
        query = settings_query(qa)
        qa.cmd('choose', widget={**query, 'prop': 'mixar_zen_sample_target'}, item='Viewport Samples')
        qa.cmd('set_text', widget={**query, 'prop': 'taa_samples'}, text='40')
        assert qa.eval(SETUP + 'result=scene.eevee.taa_samples') == 40
        snap(qa, 'compact-samples')
        dismiss(qa, query)
        assert qa.find(**HEADER, op='MIXAR_OT_director_enter')['widgets']
        assert qa.find(**HEADER, op='MIXAR_OT_zen_toggle_guides')['widgets']
        bounds = qa.eval(SETUP + "result=[area.x, area.x+area.width]")
        for widget in qa.find(**HEADER)['widgets']:
            if widget['type'] in {'Label', 'Other'}:
                continue
            assert bounds[0] <= widget['rect'][0] < widget['rect'][2] <= bounds[1], widget
            assert '…' not in widget.get('text', ''), widget
        snap(qa, 'compact-toolbar')
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved}; result=True')
    return {'viewport_samples': 40, 'cinema_and_grid_visible': True}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    reset_zen_scene(qa)
    qa.wait("hasattr(bpy.context.window_manager, 'mixar_zen_sample_target')", timeout=10)
    snap(qa, 'toolbar-start')
    checks = {}
    for name, fn in [('grid', grid), ('samples', samples), ('cinema', cinema),
                     ('sky-and-drawer', sky_and_drawer), ('compact', compact)]:
        checks[name] = qa.step(name, fn, qa)
    verdict = {'checks': checks, 'paid_requests': 0, 'artifacts': str(OUT)}
    (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2) + '\n')
    return verdict


if __name__ == '__main__':
    run_scenario('zen_toolbar_controls_e2e', run)
