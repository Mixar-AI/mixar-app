#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real Cinema and Moodboard motion, native actions, and zero paid generation.

QA_HARNESS=/path/to/harness QA_SCENARIO_OUT=/tmp/zen-chrome \
  python3 tests/qa/zen_chrome_motion_e2e.py

Requires a main viewport large enough to show the designed Cinema columns.
Review the full-window PNGs and temporal contact sheets/GIFs with the verdict.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from compact_agent_bubble_e2e import _hover_off, _hover_on
from zen_motion_capture import contact_sheet, hover, preview
from PIL import Image


INTERPOLATION = {
    'area_type': 'VIEW_3D', 'region_type': 'WINDOW',
    'text': 'Interpolation: how the camera eases between keyframes',
}
GRID = {'area_type': 'VIEW_3D', 'region_type': 'WINDOW',
        'op': 'MIXAR_OT_director_toggle_grid'}
EXPORT = {'surface': 'director_export'}
SHOT = 'drv.main_window().scene.mixar_director.shots[drv.main_window().scene.mixar_director.active_shot_index]'


def picture(qa, path):
    return qa.eval(f'''
def capture():
    yield .3
    win = drv.main_window()
    with bpy.context.temp_override(window=win):
        return win.mixar_qa_capture_frame(filepath={str(path)!r})
result=capture()
''')


def moodboard_fixture(qa):
    """A local draft with one real schema checkbox; no model is submitted."""
    return qa.eval('''
def prepare():
    win = drv.main_window()
    scene = win.scene
    area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'),
               key=lambda a: a.width*a.height)
    original = {'area': list(win.screen.areas).index(area), 'type': area.type,
                'active': scene.mixie_moodboard_active_node_id,
                'selected': [n.node_id for n in scene.mixie_moodboard_action_nodes if n.selected]}
    area.type = 'MIXIE'
    yield .35
    region = next(r for r in area.regions if r.type == 'WINDOW')
    # Derive canvas coordinates through the real View2D, so the normal node
    # layout and native QA targets determine every subsequent input rectangle.
    cx, cy = int(region.width*.64), int(region.height*.53)
    half_w = int(max(420, min(900, region.width*.32))*.5)
    half_h = int(max(260, min(650, region.height*.48))*.5)
    left, bottom = region.view2d.region_to_view(cx-half_w, cy-half_h)
    right, top = region.view2d.region_to_view(cx+half_w, cy+half_h)
    for node in scene.mixie_moodboard_action_nodes:
        node.selected = False
    node = scene.mixie_moodboard_action_nodes.add()
    node.node_id = 'qa-zen-motion-'+__import__('uuid').uuid4().hex
    node.action_type = 'IMAGE_GEN'
    node.position_x, node.position_y = left, bottom
    node.width, node.height = right-left, top-bottom
    node.prompt = 'Local motion fixture. Never submit.'
    node.show_mode = False
    node.selected = True
    scene.mixie_moodboard_active_node_id = node.node_id
    parameter = node.parameters.add()
    parameter.name = 'qa_motion_switch'
    parameter.label = 'Motion QA switch'
    parameter.parameter_type = 'BOOLEAN'
    parameter.value_boolean = False
    original['node_id'] = node.node_id
    area.tag_redraw()  # Initial fixture materialization, never a frame pump.
    yield .5
    return original
result=prepare()
''')


def cleanup_fixture(qa, fixture):
    if not fixture:
        return
    qa.eval(f'''
saved = {fixture!r}
win = drv.main_window()
scene = win.scene
nodes = scene.mixie_moodboard_action_nodes
for index in reversed(range(len(nodes))):
    if nodes[index].node_id == saved['node_id']:
        nodes.remove(index)
for node in nodes:
    node.selected = node.node_id in saved['selected']
scene.mixie_moodboard_active_node_id = saved['active']
win.screen.areas[saved['area']].type = saved['type']
result=True
''')


def select_checkbox(qa, query, output):
    output.mkdir(parents=True, exist_ok=True)
    frames = qa.eval(f'''
def capture():
    import time
    target = drv.find_one(**{query!r})
    win = target['_win']
    x, y = target['center']
    x0, y0, x1, y1 = target['rect']
    drv.move_to(win, x, y)
    yield .25
    began = time.monotonic()
    frames = []
    drv._sim(win, type='LEFTMOUSE', value='PRESS', x=x, y=y)
    drv._sim(win, type='LEFTMOUSE', value='RELEASE', x=x, y=y)
    while time.monotonic()-began < .55:
        target = drv.find_one(**{query!r})
        path = {str(output)!r}+'/frame-%03d.png' % len(frames)
        with bpy.context.temp_override(window=win):
            assert win.mixar_qa_capture_frame(filepath=path, x=x0, y=y0,
                                              width=x1-x0, height=y1-y0)
        frames.append(dict(time=time.monotonic()-began, path=path,
                           motion=target['mixar_motion'], rect=target['rect']))
        yield .02
    return frames
result=capture()
''')
    values = [frame['motion']['selected'] for frame in frames]
    assert values[0] == 0 and values[-1] == 1, values
    assert sum(0 < value < 1 for value in values) >= 3, values
    assert all(a <= b for a, b in zip(values, values[1:])), values
    assert len({tuple(frame['rect']) for frame in frames}) == 1
    pixels = []
    for frame in frames:
        with Image.open(frame['path']) as image:
            pixels.append(image.tobytes())
    assert len(set(pixels)) >= 4, 'Checkbox selection did not paint intermediate poses'
    (output/'samples.json').write_text(json.dumps(frames, indent=2)+'\n')
    preview(frames, output/'motion.gif')
    contact_sheet(frames, output/'frames.png')
    return {'selected': values, 'appearances': len(set(pixels))}


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/zen-chrome-motion'))
    out.mkdir(parents=True, exist_ok=True)
    qa.step('ready', qa.cmd, 'wait_login', timeout=60)
    qa.step('hold_island_during_native_input', _hover_off, qa)
    fixture = None
    results = {}
    try:
        # An expanded floating island can cover the dock. The bubble wmWindow
        # stays in the manager after minimise; only the native orderOut hides it.
        qa.eval("bpy.ops.mixar.bubble_minimise(); result=True")
        qa.eval('''
def settle():
    yield 0.35
    return True
result=settle()
''')
        if not qa.eval('result=drv.main_window().scene.mixar_director.is_directing'):
            qa.step('enter_cinema_from_topbar', qa.click, op='MIXAR_OT_director_enter')
        qa.step('cinema_session_active', qa.wait,
                'drv.main_window().scene.mixar_director.is_directing', timeout=15)
        has_camera = qa.eval('result=drv.main_window().scene.camera is not None and '
                             'bool(drv.main_window().scene.mixar_director.shots)')
        if not has_camera:
            qa.step('cinema_start_control', qa.wait,
                    "bool(drv.find(op='MIXAR_OT_director_start'))", timeout=15)
            qa.step('create_local_camera_shot', qa.click, op='MIXAR_OT_director_start')
        qa.step('wide_cinema_targets', qa.wait,
                "bool(drv.find(surface='director_export')) and "
                f"bool(drv.find(**{INTERPOLATION!r}))", timeout=15)
        picture(qa, out/'cinema-wide.png')
        results['cinema-popup'] = qa.step('cinema_popup_hover_reverse_idle', hover, qa,
                                          INTERPOLATION, EXPORT, out/'cinema-popup')
        results['cinema-icon'] = qa.step('cinema_icon_hover_reverse_idle', hover, qa,
                                         GRID, EXPORT, out/'cinema-icon')
        floor = "next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').spaces.active.overlay.show_floor"
        was_grid = qa.eval(f'result={floor}')
        qa.step('native_grid_icon_click', qa.click, **GRID)
        qa.step('native_grid_state_changed', qa.wait, f'{floor} == {not was_grid!r}', timeout=8)
        picture(qa, out/'cinema-grid-changed.png')
        qa.click(**GRID)
        qa.wait(f'{floor} == {was_grid!r}', timeout=8)

        previous = qa.eval(f'result={SHOT}.interpolation')
        choice, label = ('CONSTANT', 'Constant') if previous == 'LINEAR' else ('LINEAR', 'Linear')
        qa.step('open_real_interpolation_popup', qa.click, **INTERPOLATION)
        qa.wait(f"bool(drv.find(popup=True, text={label!r}))", timeout=8)
        picture(qa, out/'cinema-interpolation-popup.png')
        qa.step('choose_interpolation', qa.click, popup=True, text=label)
        qa.step('interpolation_state_changed', qa.wait, f'{SHOT}.interpolation == {choice!r}', timeout=8)
        results['interpolation'] = {'before': previous, 'after': choice}
        qa.eval(f'{SHOT}.interpolation={previous!r}; result=True')
        qa.step('leave_cinema', qa.click, op='MIXAR_OT_director_finish')
        qa.wait('not drv.main_window().scene.mixar_director.is_directing', timeout=8)

        fixture = qa.step('local_moodboard_draft', moodboard_fixture, qa)
        switch = {'area_type': 'MIXIE', 'region_type': 'WINDOW', 'text': 'Motion QA switch'}
        generate = {'area_type': 'MIXIE', 'region_type': 'WINDOW',
                    'op': 'MIXIE_OT_moodboard_run_action_node', 'text': 'Generate'}
        reset = {'area_type': 'MIXIE', 'region_type': 'WINDOW',
                 'op': 'MIXIE_OT_moodboard_reset_node_params'}
        qa.step('moodboard_native_controls_visible', qa.wait,
                f'bool(drv.find(**{switch!r})) and bool(drv.find(**{generate!r}))', timeout=15)
        picture(qa, out/'moodboard-controls.png')
        results['moodboard-toggle'] = qa.step('moodboard_toggle_hover_reverse_idle', hover, qa,
                                             switch, reset, out/'moodboard-toggle')
        results['moodboard-action'] = qa.step('moodboard_generate_hover_only', hover, qa,
                                             generate, reset, out/'moodboard-action')
        node = f"next(n for n in drv.main_window().scene.mixie_moodboard_action_nodes if n.node_id=={fixture['node_id']!r})"
        results['moodboard-selection'] = qa.step('native_schema_checkbox_selection',
            select_checkbox, qa, switch, out/'moodboard-selection')
        qa.step('native_schema_value_changed', qa.wait, f'{node}.parameters[0].value_boolean', timeout=8)
        picture(qa, out/'moodboard-checkbox-on.png')
        assert qa.eval(f'result={node}.state') == 'DRAFT'
        results['moodboard_state'] = {'checkbox': True, 'node': 'DRAFT'}
        results['paid_requests'] = 0
        results['deferred'] = ['Compact Cinema fallback at narrow viewport sizes',
                               'Zen/Engine workspace transition',
                               'Direct native slider, numeric and rename editing']
        (out/'verdict.json').write_text(json.dumps(results, indent=2)+'\n')
        return results
    finally:
        for popup in qa.find(popup=True)['widgets'][:1]:
            qa.press('ESC', window=popup['window'])
        cleanup_fixture(qa, fixture)
        _hover_on(qa)


if __name__ == '__main__':
    run_scenario('zen_chrome_motion_e2e', run)
