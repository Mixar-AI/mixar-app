# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit real-input regression for the fixed Zen toolbar's covered sash.

Run through windows_ui_capture for independent desktop composition captures.
All scales are checked even on an unfixed build, then any missed menu fails.
The toolbar remains visible; hiding it is not accepted as a product fix.
"""
import json
import os
from pathlib import Path
import time

from moodboard_drawer_e2e import geometry, toggle

MODE_ZEN = {'area_type': 'TOPBAR', 'op': 'MIXAR_OT_set_ui_mode_ai'}
MODE_ENGINE = {'area_type': 'TOPBAR', 'op': 'MIXAR_OT_set_ui_mode_pro'}

BOARD = {'text': 'Arrange, frame, or clear the board'}
FRAME = {'popup': True, 'op': 'MIXIE_OT_moodboard_frame'}


def regions(qa):
    return qa.eval("w=drv.main_window();a=next(a for a in w.screen.areas if a.type=='VIEW_3D');"
        "result={'toolbar':a.spaces.active.show_region_toolbar,"
        "'sidebar':a.spaces.active.show_region_ui,"
        "'scale':bpy.context.preferences.system.ui_scale,"
        "'regions':{r.type:[r.x,r.y,r.x+r.width,r.y+r.height] for r in a.regions}}")


def capture(qa, out, label):
    qa.cmd('snap', path=str(out / (label + '.png')))


def menu_at_scale(qa, out, scale):
    qa.eval(f'bpy.context.preferences.view.ui_scale={scale};result=True')
    time.sleep(.4)
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    state = geometry(qa)
    grip = qa.find(surface='moodboard_drawer_grip')['widgets'][0]
    # Stored width can exceed the currently clamped width after UI scaling.
    # Drag the actual grip to the observed viewport edge, not a stored delta.
    qa.cmd('drag', **{'from': {'surface': 'moodboard_drawer_grip'},
        'to': {'x': state['viewport'][0] + 1, 'y': grip['center'][1]}, 'steps': 12})
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .998', timeout=4)
    time.sleep(.3)
    before = regions(qa)
    assert before['toolbar'], 'Regression requires visible underlying toolbar'
    button = qa.find(**BOARD)['widgets'][0]
    edge = before['regions']['TOOLS'][2]
    # Both the fixed toolbar and board button scale from the same UI units.
    assert abs(button['center'][0] - edge) <= 2, (button, before)
    label = 'board-' + str(scale)
    capture(qa, out, label + '-before')
    qa.click(**BOARD)
    try:
        qa.wait(f'bool(drv.find(**{FRAME!r}))', timeout=3)
        opened = True
    except Exception as error:
        opened = False
        reason = str(error)
    capture(qa, out, label + '-after')
    result = {'scale': scale, 'before': before, 'button': button,
              'opened': opened, 'error': None if opened else reason}
    qa.press('ESC')
    qa.wait('not drv.find(popup=True)', timeout=3)
    toggle(qa, 0)
    qa.wait('not drv.find(surface="moodboard_drawer_panel")', timeout=4)
    qa.wait('bool(drv.find(area_type="VIEW_3D",op="WM_OT_tool_set_by_id"))', timeout=3)
    tool_targets = qa.find(area_type='VIEW_3D', op='WM_OT_tool_set_by_id')
    capture(qa, out, label + '-toolbar-before-click')
    active = qa.eval("def choose():\n"
        " ts=sorted(drv.find(area_type='VIEW_3D',op='WM_OT_tool_set_by_id'),key=lambda t:-t['center'][1])\n"
        " assert len(ts)==3\n"
        " yield from drv.click_steps(ts[0])\n yield .2\n"
        " assert drv.main_window().workspace.tools.from_space_view3d_mode('OBJECT').idname=='builtin.move'\n"
        " yield from drv.click_steps(ts[1])\n yield .2\n"
        " return drv.main_window().workspace.tools.from_space_view3d_mode('OBJECT').idname\nresult=choose()")
    (out / (label + '-tool-state.json')).write_text(json.dumps(
        {'targets': tool_targets, 'active_after': active}, indent=2))
    capture(qa, out, label + '-toolbar-after-click')
    assert active == 'builtin.rotate', active
    capture(qa, out, label + '-toolbar-rotate')
    toggle(qa, 1)
    result['toolbar_click'] = active
    result['grip_close_reopen'] = geometry(qa)['amount'] > .998
    return result


def engine_resize(qa, out):
    qa.eval('bpy.context.preferences.view.ui_scale=1.0;result=True')
    qa.click(**MODE_ENGINE)
    time.sleep(.4)
    before = regions(qa)
    if not before['toolbar']:
        qa.eval("w=drv.main_window();a=next(a for a in w.screen.areas if a.type=='VIEW_3D');"
                "r=next(r for r in a.regions if r.type=='WINDOW');"
                "drv.move_to(w,r.x+r.width//2,r.y+r.height//2);result=True")
        qa.press('T')
        qa.wait("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').spaces.active.show_region_toolbar", timeout=4)
        before = regions(qa)
    rect = before['regions']['TOOLS']
    # Blender clips an overlapping toolbar's resize zone to its content.
    # A tall Retina window's region midpoint can be below every control.
    query = {'area_type': 'VIEW_3D', 'region_type': 'TOOLS',
             'op': 'WM_OT_tool_set_by_id'}
    qa.wait(f'bool(drv.find(**{query!r}))', timeout=3)
    target = max(qa.find(**query)['widgets'], key=lambda item: item['center'][1])
    x, y = rect[2] - 1, target['center'][1]
    assert rect[1] < y < rect[3], (target, before)
    capture(qa, out, 'engine-toolbar-before')
    qa.cmd('drag', **{'from': {'x': x, 'y': y}, 'to': {'x': x + 70, 'y': y}, 'steps': 12})
    after = regions(qa)
    assert after['regions']['TOOLS'][2] > rect[2] + 20, (before, after)
    capture(qa, out, 'engine-toolbar-expanded')
    x1 = after['regions']['TOOLS'][2] - 1
    qa.cmd('drag', **{'from': {'x': x1, 'y': y}, 'to': {'x': x, 'y': y}, 'steps': 12})
    restored = regions(qa)
    capture(qa, out, 'engine-toolbar-restored')
    return {'before': before, 'after': after, 'restored': restored,
            'resize_row': target, 'gesture': [x, y, x + 70, y]}


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT'])
    original_scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    results = []
    try:
        qa.click(**MODE_ZEN)
        for scale in (1.0, 1.25, 1.5):
            results.append(menu_at_scale(qa, out, scale))
            (out / 'hit-zones-state.json').write_text(json.dumps(results, indent=2))
        engine = engine_resize(qa, out)
        (out / 'engine-resize-state.json').write_text(json.dumps(engine, indent=2))
        assert all(row['opened'] for row in results), 'Visible Board button lost clicks to underlying toolbar resize zone'
        return {'scales': results, 'engine_resize': engine, 'backend_submissions': 0}
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={original_scale};result=True')
        qa.click(**MODE_ZEN)
