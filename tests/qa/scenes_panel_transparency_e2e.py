#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Scenes drawer compositor regression, driven by native QA clicks.

Launch a fresh isolated Dev app with the installed QA harness, then run:
QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4798 \\
  QA_SCENARIO_OUT=build/qa/scenes-transparency \\
  python3 tests/qa/scenes_panel_transparency_e2e.py

Checks startup readiness, retains two scenes and the open drawer through repeated
Zen/Engine switches, verifies clipping and stock-header targets, and tests the
exposed strip's pixels (including bottom-aligned Tool Settings). Saves full
screenshots and strip crops for visual review. Does not send agent prompts.
"""
import inspect
import os
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

WM = 'bpy.context.window_manager'


def flush_window():
    win = drv.main_window()
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    return True


def geometry():
    win = drv.main_window()
    hosts = [a for a in win.screen.areas
             if a.type == 'VIEW_3D' and a.mixar_scenes_drawer_hosts()]
    assert len(hosts) == 1, ('one drawer host', len(hosts))
    area = hosts[0]
    regions = {r.type: r for r in area.regions}
    drawer = regions['NAVIGATION_BAR']
    viewport = regions['WINDOW']
    assert viewport.x >= drawer.x + drawer.width, 'viewport stays right of drawer'
    assert len(drv.find(surface='scenes_drawer_panel')) == 1
    cards = drv.find(surface='scenes_drawer_card')
    assert len(cards) == 2 and sum(bool(c.get('sel')) for c in cards) == 1, cards
    assert bpy.context.window_manager.mixar_scenes_drawer_target == 1
    assert bpy.context.window_manager.mixar_scenes_drawer_amount >= .98
    tool = regions['TOOL_HEADER']
    below = tool.y < drawer.y
    assert tool.y + tool.height <= drawer.y if below else drawer.y + drawer.height <= tool.y
    # Object-mode Tool Settings puts selection controls at the left; the right
    # half of the drawer column has no controls. Exclude all widget rectangles.
    rect = [int(drawer.x + drawer.width * .55), int(tool.y + tool.height * .2),
            int(drawer.x + drawer.width * .92), int(tool.y + tool.height * .8)]
    for widget in drv.find(area_type='VIEW_3D', region_type='TOOL_HEADER'):
        w = widget['rect']
        assert w[2] <= rect[0] or w[0] >= rect[2] or w[3] <= rect[1] or w[1] >= rect[3], (
            'pixel probe must exclude real controls', widget, rect)
    assert drv.find(op='VIEW3D_OT_scenes_drawer_toggle', region_type='HEADER')
    assert drv.find(prop='ui_type', area_type='VIEW_3D', region_type='HEADER')
    return {'probe': rect, 'window_size': [win.width, win.height],
            'drawer_width': drawer.width, 'bottom_strip': below}


def flip_tool_header():
    win = drv.main_window()
    area = next(a for a in win.screen.areas
                if a.type == 'VIEW_3D' and a.mixar_scenes_drawer_hosts())
    region = next(r for r in area.regions if r.type == 'TOOL_HEADER')
    with bpy.context.temp_override(window=win, area=area, region=region):
        result = bpy.ops.screen.region_flip()
    assert 'FINISHED' in result, result
    return True


def check_pixels(qa, out, label):
    qa.eval('result=flush_window()')
    g = qa.eval('result=geometry()')
    path = out / f'{label}.png'
    qa.snap(str(path))
    with Image.open(path) as image:
        # Native dump/event coordinates share the screenshot's pixel space.
        x0, y0, x1, y1 = g['probe']
        assert 0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height, g
        crop = image.convert('RGB').crop((x0, image.height-y1, x1, image.height-y0))
        crop.save(out / f'{label}-strip.png')
        ranges = [hi-lo for lo, hi in crop.getextrema()]
    assert max(ranges) <= 2, ('stale pixels under transparent Tool Settings', ranges, g)
    return {**g, 'channel_ranges': ranges, 'screenshot': str(path)}


def resize_drawer(qa, delta):
    qa.eval('result=flush_window()')
    edge = qa.find(surface='scenes_drawer_edge')['widgets'][0]['rect']
    qa.cmd('drag', **{'from': {'surface': 'scenes_drawer_edge'},
                     'to': {'x': (edge[0]+edge[2])//2 + delta,
                            'y': (edge[1]+edge[3])//2}})


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', 'build/qa/scenes-transparency')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.step('event_simulation', qa.cmd, 'ping')
    qa.wait(f"{WM}.mixie_chat_is_logged_in and drv.main_window().scene.mixie_chat_state=='IDLE'",
            timeout=30)
    qa.eval("assert __import__('os').environ.get('MIXAR_QA')=='1'\n"
            f"assert hasattr({WM}, 'mixar_qa_ui_dump')\n"
            'assert bpy.app.use_event_simulate\nresult=True')
    helpers = '\n'.join(inspect.getsource(fn) for fn in (flush_window, geometry, flip_tool_header))
    native_eval = qa.eval
    qa.eval = lambda code: native_eval(helpers + '\n' + code)
    qa.eval('result=flush_window()')
    if qa.eval("result=drv.main_window().workspace.name!='Zen Mode'"):
        qa.click(op='MIXAR_OT_set_ui_mode_ai', area_type='TOPBAR')
    qa.wait("drv.main_window().workspace.name=='Zen Mode'")
    if qa.eval(f'result={WM}.mixar_scenes_drawer_target') != 1:
        qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area_type='VIEW_3D')
    qa.wait(f'{WM}.mixar_scenes_drawer_amount>=.98')
    count = qa.eval(f'result=len({WM}.mixar_scene_tabs)')
    assert count in (1, 2), 'use a fresh QA app with at most two tabs'
    if count == 1:
        qa.click(surface='scenes_drawer_new')
    qa.wait(f'len({WM}.mixar_scene_tabs)==2')
    names = qa.eval(f'result=[t.scene_name for t in {WM}.mixar_scene_tabs]')
    active = qa.eval('result=drv.main_window().scene.name')
    qa.snap(str(out / 'zen-open.png'))
    metrics = []
    for cycle in range(3):
        qa.click(op='MIXAR_OT_set_ui_mode_pro', area_type='TOPBAR')
        qa.wait("drv.main_window().workspace.name!='Zen Mode'")
        qa.eval("area=next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D' "
                "and a.mixar_scenes_drawer_hosts())\n"
                'area.spaces.active.show_region_tool_header=True\nresult=True')
        qa.wait("bool(drv.find(surface='scenes_drawer_panel'))")
        metrics.append(qa.step(f'engine_{cycle}_clean_strip', check_pixels, qa, out,
                               f'engine-{cycle}'))
        qa.step(f'engine_{cycle}_preserves_scene', qa.eval,
                f'assert drv.main_window().scene.name=={active!r}\n'
                f'assert [t.scene_name for t in {WM}.mixar_scene_tabs]=={names!r}\nresult=True')
        qa.click(op='MIXAR_OT_set_ui_mode_ai', area_type='TOPBAR')
        qa.wait("drv.main_window().workspace.name=='Zen Mode'")
        qa.wait("bool(drv.find(surface='scenes_drawer_panel'))")
    qa.snap(str(out / 'zen-round-trip.png'))
    qa.click(op='MIXAR_OT_set_ui_mode_pro', area_type='TOPBAR')
    qa.wait("drv.main_window().workspace.name!='Zen Mode'")
    qa.eval('result=flip_tool_header()')
    try:
        qa.wait("bool(drv.find(surface='scenes_drawer_panel'))")
        metrics.append(qa.step('bottom_header_clean_strip', check_pixels, qa, out, 'engine-bottom'))
        assert metrics[-1]['bottom_strip']
    finally:
        qa.eval('result=flip_tool_header()')
    initial_width = metrics[0]['drawer_width']
    qa.step('resize_native_sash', resize_drawer, qa, -120)
    metrics.append(qa.step('resized_clean_strip', check_pixels, qa, out, 'engine-resized'))
    assert metrics[-1]['drawer_width'] < initial_width
    resize_drawer(qa, initial_width - metrics[-1]['drawer_width'])
    # Retained cards remain usable after compositor and workspace changes.
    other = next(name for name in names if name != active)
    qa.click(surface='scenes_drawer_card', text=other)
    qa.wait(f'drv.main_window().scene.name=={other!r}')
    qa.step('cards_still_switch', qa.eval, 'result=geometry()')
    qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area_type='VIEW_3D')
    qa.wait(f'{WM}.mixar_scenes_drawer_amount<=.01')
    qa.step('closed_drawer_has_no_targets', qa.eval,
            "assert not drv.find(surface='scenes_drawer_panel')\nresult=True")
    qa.snap(str(out / 'engine-closed.png'))
    return {'no_credits': True, 'mode_round_trips': 3, 'strips': metrics,
            'screenshots': str(out)}


if __name__ == '__main__':
    run_scenario('scenes_panel_transparency_e2e', run)
