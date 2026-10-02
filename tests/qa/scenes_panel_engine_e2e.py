#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Scenes drawer in Engine Mode: no-credit native replay.

Run startup_health first in a fresh isolated QA app, then:
QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4796 \\
  python3 tests/qa/scenes_panel_engine_e2e.py

Asserts that the Scenes hamburger heads the stock header of the main 3D View
only; that it opens the drawer there below a visible Tool Settings strip with
the toolbar and viewport pushed right; that "+ New scene" and the cards add and
switch tabs; that Ctrl+` toggles from the viewport and from the Outliner; that
a split layout shows one panel, on its largest 3D View; and that the open state
carries across Zen and Engine. Read the saved screenshots for visual QA.
"""
import inspect
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

WM = 'bpy.context.window_manager'
SPLIT_WORKSPACE = 'QA Engine Scenes'


def host_area():
    """Injected into the app: the one 3D View that says it hosts the drawer."""
    win = drv.main_window()
    views = [a for a in win.screen.areas if a.type == 'VIEW_3D']
    hosts = [a for a in views if a.mixar_scenes_drawer_hosts()]
    assert len(hosts) == 1, ('one host per window', len(hosts), len(views))
    largest = max(views, key=lambda a: a.width * a.height)
    assert hosts[0] == largest, ('the largest 3D View hosts', hosts[0].width, largest.width)
    return hosts[0]


def inside(rect, area):
    return area.x <= rect[0] and rect[2] <= area.x + area.width


def toggle_heads_host_header():
    host = host_area()
    toggles = drv.find(op='VIEW3D_OT_scenes_drawer_toggle', area_type='VIEW_3D',
                       region_type='HEADER')
    assert len(toggles) == 1, ('one toggle, on the host', toggles)
    rect = toggles[0]['rect']
    assert inside(rect, host), (rect, host.x, host.width)
    # Prepended to the stock header: the Editor Type dropdown follows it.
    editor_type = [w for w in drv.find(prop='ui_type', area_type='VIEW_3D', region_type='HEADER')
                   if inside(w['rect'], host)]
    assert editor_type, 'the stock header is still drawn'
    assert rect[2] <= editor_type[0]['rect'][0] + 1, (rect, editor_type[0]['rect'])
    return {'toggle': rect, 'editor_type': editor_type[0]['rect']}


def engine_panel_geometry():
    host = host_area()
    regions = {r.type: r for r in host.regions}
    panels = drv.find(surface='scenes_drawer_panel')
    assert len(panels) == 1, panels
    panel = panels[0]['rect']
    new = drv.find_one(surface='scenes_drawer_new')['rect']
    assert inside(panel, host), (panel, host.x, host.width)
    header = regions['HEADER']
    assert panel[3] < header.y, ('panel below the header', panel, header.y)
    tool_header = regions.get('TOOL_HEADER')
    if host.spaces.active.show_region_tool_header and tool_header and tool_header.height > 1:
        # Engine's Tool Settings strip overlaps the viewport top; the drawer
        # starts below it, so "+ New scene" is never under its buttons.
        assert panel[3] < tool_header.y, ('panel below Tool Settings', panel, tool_header.y)
        assert new[3] < tool_header.y, (new, tool_header.y)
    assert panel[1] < new[1] < new[3] < panel[3], (panel, new)
    window = regions['WINDOW']
    assert window.x >= panel[2], ('viewport pushed right', window.x, panel)
    tools = regions.get('TOOLS')
    if tools is not None and tools.width > 1:
        assert tools.x >= panel[2], ('toolbar pushed right', tools.x, panel)
    return {'panel': panel, 'new': new, 'window_x': window.x,
            'tools_x': tools.x if tools is not None else None}


def pointer_over(area_type):
    """Rest the pointer on `area_type`'s main region (the host for VIEW_3D)."""
    win = drv.main_window()
    area = host_area() if area_type == 'VIEW_3D' else next(
        a for a in win.screen.areas if a.type == area_type)
    region = next(r for r in area.regions if r.type == 'WINDOW')
    drv.move_to(win, region.x + region.width // 2, region.y + region.height // 2)
    return True


def toggle_shortcut(qa, area_type):
    """Ctrl+` over `area_type`: the drawer's shortcut in every editor."""
    qa.eval(f'result=pointer_over({area_type!r})')
    qa.press('ACCENT_GRAVE', ctrl=True)


def split_host(factor):
    win = drv.main_window()
    host = host_area()
    region = next(r for r in host.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=win, area=host, region=region):
        result = bpy.ops.screen.area_split(direction='VERTICAL', factor=factor)
    assert 'FINISHED' in result, result
    return True


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/scenes-panel-engine-qa')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA') == '1'\nresult=True")
    qa.dismiss_splash()
    qa.wait(f"hasattr({WM}, 'mixar_scene_tabs')", timeout=30)
    helpers = '\n'.join(inspect.getsource(fn) for fn in (
        host_area, inside, toggle_heads_host_header, engine_panel_geometry,
        pointer_over, split_host))
    native_eval = qa.eval
    qa.eval = lambda code: native_eval(helpers + '\n' + code)
    qa.eval(f"assert len({WM}.mixar_scene_tabs)==1, 'Use a fresh isolated QA profile'\nresult=True")
    zen_at_start = qa.eval("result=drv.main_window().workspace.name == 'Zen Mode'")
    try:
        if zen_at_start:
            qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_pro')
        qa.wait("drv.main_window().workspace.name != 'Zen Mode'", timeout=10)
        qa.wait("bool(drv.find(prop='ui_type', area_type='VIEW_3D', region_type='HEADER'))",
                timeout=10)
        if qa.eval(f'result={WM}.mixar_scenes_drawer_target') == 1:
            qa.eval("import bpy\nwin=drv.main_window()\n"
                    "with bpy.context.temp_override(window=win):\n"
                    "    bpy.ops.view3d.scenes_drawer_toggle()\nresult=True")
        qa.wait(f'{WM}.mixar_scenes_drawer_amount <= .01')

        # Tool Settings visible: the strip that overlaps the viewport top.
        qa.eval('host_area().spaces.active.show_region_tool_header = True\nresult=True')
        qa.step('toggle_heads_main_header', qa.eval, 'result=toggle_heads_host_header()')
        qa.snap(str(out / 'engine-shut.png'))

        qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
        qa.wait(f'{WM}.mixar_scenes_drawer_amount >= .98')
        qa.step('open_geometry', qa.eval, 'result=engine_panel_geometry()')
        qa.snap(str(out / 'engine-open.png'))

        first = qa.eval(f'result={WM}.mixar_scene_tabs[0].scene_name')
        qa.click(surface='scenes_drawer_new')
        qa.wait(f'len({WM}.mixar_scene_tabs)==2')
        second = qa.eval(f'result=[t.scene_name for t in {WM}.mixar_scene_tabs if t.scene_name!={first!r}][0]')
        qa.wait(f'drv.main_window().scene.name=={second!r}')
        qa.click(surface='scenes_drawer_card', text=first)
        qa.wait(f'drv.main_window().scene.name=={first!r}')
        qa.step('cards_switch_tabs', qa.eval,
                f"assert drv.find_one(surface='scenes_drawer_card', text={first!r})['sel']\n"
                'result=engine_panel_geometry()')
        qa.snap(str(out / 'engine-two-scenes.png'))

        # Ctrl+` is the drawer's shortcut in Engine too (it shadows Blender's
        # gizmo toggle in the 3D View, as it already did in Zen).
        gizmos = qa.eval('result=host_area().spaces.active.show_gizmo')
        toggle_shortcut(qa, 'VIEW_3D')
        qa.wait(f'{WM}.mixar_scenes_drawer_amount <= .01')
        qa.step('shortcut_from_viewport', qa.eval,
                f'assert host_area().spaces.active.show_gizmo == {gizmos!r}\n'
                "assert not drv.find(surface='scenes_drawer_panel')\nresult=True")
        if qa.eval("result=any(a.type=='OUTLINER' for a in drv.main_window().screen.areas)"):
            toggle_shortcut(qa, 'OUTLINER')
            qa.wait(f'{WM}.mixar_scenes_drawer_amount >= .98')
            qa.step('shortcut_from_outliner', qa.eval, 'result=engine_panel_geometry()')
        else:
            qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
            qa.wait(f'{WM}.mixar_scenes_drawer_amount >= .98')

        # A split layout: one panel, on the larger 3D View, one toggle.
        layout_name = qa.eval('result=drv.main_window().workspace.name')
        qa.eval("import bpy\nwin=drv.main_window()\n"
                "with bpy.context.temp_override(window=win):\n"
                "    bpy.ops.workspace.duplicate()\n"
                f"win.workspace.name={SPLIT_WORKSPACE!r}\nresult=True")
        qa.wait(f"drv.main_window().workspace.name=={SPLIT_WORKSPACE!r}")
        views = qa.eval("result=len([a for a in drv.main_window().screen.areas if a.type=='VIEW_3D'])")
        qa.eval('result=split_host(0.3)')
        qa.wait("len([a for a in drv.main_window().screen.areas if a.type=='VIEW_3D'])"
                f"=={views + 1}")
        qa.wait("bool(drv.find(surface='scenes_drawer_panel'))")
        qa.step('split_layout_one_panel', qa.eval,
                'geometry=engine_panel_geometry()\n'
                'geometry.update(toggle_heads_host_header())\nresult=geometry')
        qa.snap(str(out / 'engine-split.png'))
        qa.eval("import bpy\nwin=drv.main_window()\n"
                "with bpy.context.temp_override(window=win):\n"
                "    bpy.ops.workspace.delete()\n"
                f"win.workspace=bpy.data.workspaces[{layout_name!r}]\nresult=True")
        qa.wait(f"drv.main_window().workspace.name=={layout_name!r}")

        # One open state for the whole app: Zen shows the same drawer.
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
        qa.wait("drv.main_window().workspace.name == 'Zen Mode'", timeout=10)
        qa.wait("bool(drv.find(surface='scenes_drawer_panel'))")
        qa.snap(str(out / 'zen-carries-open.png'))
        qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
        qa.wait(f'{WM}.mixar_scenes_drawer_amount <= .01')
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_pro')
        qa.wait("drv.main_window().workspace.name != 'Zen Mode'", timeout=10)
        qa.step('engine_carries_shut', qa.eval,
                f"assert {WM}.mixar_scenes_drawer_amount <= .01\n"
                "assert not drv.find(surface='scenes_drawer_panel')\n"
                'result=toggle_heads_host_header()')
        qa.snap(str(out / 'engine-carries-shut.png'))
    finally:
        if zen_at_start:
            qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    return {'engine_toggle': True, 'tool_settings_clip': True, 'cards': True,
            'shortcut': True, 'split_layout': True, 'mode_round_trip': True,
            'screenshots': str(out)}


if __name__ == '__main__':
    run_scenario('scenes_panel_engine_e2e', run)
