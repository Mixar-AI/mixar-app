#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Zen menu bar + scene toolbar across real window widths; no paid requests.

Resizes the isolated QA host window (macOS) from wide to narrow at 1x UI
scale, logged out and with a long fake account email, and asserts:
- the scene toolbar picks the widest tier that fits (inline render settings at
  1512 logical pixels), its controls stay inside the header and never overlap;
- menu-bar widgets never overlap the centred mode slider or each other, and
  the slider stays centred on the window;
- the Scene Controls popover holds what the tier removed.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT against an isolated
Dev app, then review every emitted capture alongside the verdict.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/zen-topbar-responsive'))
WIDTHS = (1800, 1512, 1280, 1100, 900, 760, 640, 560)
EMAIL = 'someone.with.a.long.name@example-company.com'
SLIDER_OPS = {'MIXAR_OT_set_ui_mode_ai', 'MIXAR_OT_set_ui_mode_pro'}

GEOMETRY = '''
w = drv.main_window()
s = bpy.context.preferences.system
from mixar.modules.workflow.core import zen_toolbar_layout as t
view = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
header = next(r for r in view.regions if r.type == 'HEADER')
bar = next(a for a in w.global_areas if a.type == 'TOPBAR')
lanes = sorted([r.x, r.x + r.width] for r in bar.regions
               if r.type == 'HEADER' and r.width > 1)
result = {'win_px': w.width * s.pixel_size, 'scale': s.ui_scale, 'lanes': lanes,
          'header': [header.x, header.x + header.width],
          'tier': t.tier_for_width(header.width / s.ui_scale)}
'''


def visible(widgets):
    return [x for x in widgets if x['type'] != 'Other' and x['rect'][2] > x['rect'][0]]


def overlaps(a, b, tol=1):
    return (min(a[2], b[2]) - max(a[0], b[0]) > tol and
            min(a[3], b[3]) - max(a[1], b[1]) > tol)


def native(qa, **kwargs):
    return qa.eval(f'import zen_ui_native as n; result=n.frame("host", **{kwargs!r})')


def check_width(qa, width, account, scale=1.0):
    native(qa, size=(width, native(qa)[3]))
    qa.eval(f'bpy.context.preferences.view.ui_scale = {scale!r}\nresult = True')
    time.sleep(.8)
    if account == 'logged_out':
        # The QA profile's session can re-assert login; draw logged out.
        qa.eval('bpy.context.window_manager.mixie_chat_is_logged_in = False\nresult = True')
        time.sleep(.3)
    geo = qa.eval(GEOMETRY)
    tag = f'{account}-{width}' + ('' if scale == 1.0 else f'@{int(scale * 100)}')
    qa.cmd('snap', path=str(OUT / f'topbar-{tag}.png'), area='TOPBAR')
    qa.cmd('snap', path=str(OUT / f'toolbar-{tag}.png'), area='VIEW_3D', region='HEADER')

    # Menu bar: every widget clear of the slider and of the other region.
    bar = visible(qa.find(area_type='TOPBAR')['widgets'])
    slider = [x for x in bar if x.get('op') in SLIDER_OPS]
    assert len(slider) == 2, slider
    track = [min(x['rect'][0] for x in slider), min(x['rect'][1] for x in slider),
             max(x['rect'][2] for x in slider), max(x['rect'][3] for x in slider)]
    centre = (track[0] + track[2]) / 2
    assert abs(centre - geo['win_px'] / 2) <= 2, (track, geo)
    # The slider must sit wholly inside the left header region: the right
    # region's bounds clip it even where no widget overlaps it.
    left_lane = geo['lanes'][0]
    assert left_lane[0] <= track[0] and track[2] <= left_lane[1] + 1, ('slider clipped', track, geo)
    for x in bar:
        lane = next((l for l in geo['lanes'] if l[0] <= x['rect'][0] < l[1]), None)
        assert lane and x['rect'][2] <= lane[1] + 1, ('outside its region', x, geo)
        if x in slider:
            continue
        assert not overlaps(x['rect'], track), ('under slider', x, track)
        assert 0 <= x['rect'][0] and x['rect'][2] <= geo['win_px'] + 1, ('clipped', x, geo)
    # Both menu-bar regions report HEADER; rects are window pixels, so any
    # pair overlapping means the right lane ran into the left one.
    others = [x for x in bar if x not in slider]
    for i, a in enumerate(others):
        for b in others[i + 1:]:
            assert not overlaps(a['rect'], b['rect']), ('menu bar overlap', a, b)

    # Scene toolbar: inside the header, no two controls overlapping.
    tools = visible(qa.find(area_type='VIEW_3D', region_type='HEADER')['widgets'])
    x0, x1 = geo['header']
    for i, a in enumerate(tools):
        assert x0 <= a['rect'][0] and a['rect'][2] <= x1 + 1, ('toolbar clipped', a, geo)
        for b in tools[i + 1:]:
            assert not overlaps(a['rect'], b['rect']), ('toolbar overlap', a, b)
    add = [x for x in tools if x.get('text') == 'Add Objects']
    assert len(add) == 1 and (add[0]['rect'][2] - add[0]['rect'][0]) / geo['scale'] >= 110, add
    inline_render = any(x.get('text') == 'Render Engine' for x in tools)
    assert inline_render == (geo['tier'] == 'FULL'), (geo, inline_render)
    if width == 1512:
        assert geo['tier'] == 'FULL', geo
    cinema = qa.find(op='MIXAR_OT_director_enter', area_type='VIEW_3D', region_type='HEADER')
    assert cinema['total'] == int(geo['tier'] in ('FULL', 'COMPACT', 'NARROW')), geo

    if geo['tier'] in ('TIGHT', 'MINIMAL'):
        qa.eval('''
def open_more():
    pops = drv.find(area_type='VIEW_3D', region_type='HEADER', but_type='Popover')
    yield from drv.click_steps(pops[-1])
    yield .3
    return True
result = open_more()
''')
        qa.wait("bool(drv.find(text='Export', popup=True))", timeout=5)
        assert qa.find(op='MIXAR_OT_director_enter', popup=True)['total'] == 1
        if geo['tier'] == 'MINIMAL':
            assert qa.find(op='MIXAR_OT_zen_toggle_guides', popup=True)['total'] == 1
        qa.cmd('snap', path=str(OUT / f'overflow-{tag}.png'))
        qa.press('ESC')
    collapsed = qa.find(area_type='TOPBAR', text='File')['total'] == 0
    sound = qa.find(op='MIXIE_CHAT_OT_toggle_completion_sound', area_type='TOPBAR')['total']
    return {'tier': geo['tier'], 'menus_collapsed': collapsed, 'sound_toggle': bool(sound),
            'slider': track, 'win_px': geo['win_px']}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval(f'import sys; sys.path.insert(0,{str(Path(__file__).parent)!r}); result=True')
    saved = qa.eval('''
import os
assert os.environ.get('MIXAR_QA') == '1'
wm = bpy.context.window_manager
result = {'scale': bpy.context.preferences.view.ui_scale,
          'zen': drv.main_window().workspace.name == 'Zen Mode',
          'logged_in': bool(getattr(wm, 'mixie_chat_is_logged_in', False)),
          'email': bpy.context.scene.mixie_chat_user_id}
''')
    frame = native(qa)
    try:
        qa.cmd('dismiss_splash')
    except Exception:  # noqa: BLE001 — older harnesses lack the command
        pass
    if not saved['zen']:
        qa.click(op='MIXAR_OT_set_ui_mode_ai')
    qa.wait("drv.main_window().workspace.name == 'Zen Mode'", timeout=10)
    qa.eval('bpy.context.preferences.view.ui_scale = 1.0\nresult = True')
    results = {}
    try:
        for account in ('logged_out', 'long_email'):
            # Display-only account state: the pill reads these two properties.
            qa.eval(f'''
wm = bpy.context.window_manager
wm.mixie_chat_is_logged_in = {account != 'logged_out'}
bpy.context.scene.mixie_chat_user_id = {EMAIL!r}
result = True
''')
            for width in WIDTHS:
                results[f'{account}-{width}'] = qa.step(
                    f'{account}_{width}', check_width, qa, width, account)
            # 448 logical pixels: the narrowest tier, and the sound toggle
            # gives way so the account button never reaches the slider.
            results[f'{account}-560@125'] = qa.step(
                f'{account}_560_at_125', check_width, qa, 560, account, 1.25)
        return {'widths': results, 'backend_calls': 0}
    finally:
        native(qa, size=frame[2:])
        qa.eval(f'''
wm = bpy.context.window_manager
wm.mixie_chat_is_logged_in = {saved['logged_in']}
bpy.context.scene.mixie_chat_user_id = {saved['email']!r}
bpy.context.preferences.view.ui_scale = {saved['scale']!r}
result = True
''')


if __name__ == '__main__':
    run_scenario('zen_topbar_responsive_e2e', run)
