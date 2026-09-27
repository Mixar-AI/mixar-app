#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Header-row heights, Cinema raised V1, film strip, width and enter/finish clicks in both hosts; no paid requests.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT against an isolated
Dev app. Inspect the emitted PNGs as well as the state/pixel verdict.
"""

import os
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/cinema-button'))


def redraw(qa, code):
    return qa.eval('''
def update():
''' + '\n'.join('    ' + line for line in code.splitlines()) + '''
    for area in list(drv.main_window().screen.areas) + list(drv.main_window().global_areas):
        area.tag_redraw()
    yield .5
    return True
result = update()
''')


def capture(qa, host, name, active):
    query = {'area_type': host, 'region_type': 'HEADER',
             'op': 'MIXAR_OT_director_finish' if active else 'MIXAR_OT_director_enter'}
    hits = qa.find(**query)['widgets']
    assert len(hits) == 1, hits
    target = hits[0]
    assert target['text'] == 'Cinema Mode', target
    scale = qa.eval('result=bpy.context.preferences.system.ui_scale')
    x0, y0, x1, y1 = target['rect']
    width = (x1-x0) / scale
    height = (y1-y0) / scale
    assert abs(height-(28 if host == 'VIEW_3D' else 36)) <= 1, height
    row_heights = qa.eval("""
win = drv.main_window()
def header_height(areas, kind):
    return next(r.height for a in areas if a.type == kind for r in a.regions
                if r.type == 'HEADER') / bpy.context.preferences.system.ui_scale
result = {'topbar': header_height(win.global_areas, 'TOPBAR')}
if drv.main_window().workspace.name == 'Zen Mode':
    result['scene_toolbar'] = header_height(win.screen.areas, 'VIEW_3D')
""")
    assert abs(row_heights['topbar']-40) <= 1, row_heights
    slider = [qa.find(area_type='TOPBAR', op=op)['widgets'][0]['rect']
              for op in ('MIXAR_OT_set_ui_mode_ai', 'MIXAR_OT_set_ui_mode_pro')]
    topbar_y = qa.eval("result=next(r.y for a in drv.main_window().global_areas "
                       "if a.type=='TOPBAR' for r in a.regions if r.type=='HEADER')")
    for rect in slider:
        assert abs((rect[3]-rect[1])/scale-28) <= 1, rect
        assert abs((rect[1]+rect[3])/2-topbar_y-20*scale) <= 1, rect
    if host == 'VIEW_3D':
        assert abs(row_heights['topbar']-row_heights['scene_toolbar']) <= 1, row_heights
    if host == 'VIEW_3D':
        region_bounds = qa.eval("""
area = next(a for a in drv.main_window().screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'HEADER')
result = [region.y, region.y + region.height]
""")
        controls = qa.find(area_type=host, region_type='HEADER')['widgets']
        for control in controls:
            if control['type'] in {'Label', 'Other'}:
                continue
            bottom = (control['rect'][1] - region_bounds[0]) / scale
            top = (region_bounds[1] - control['rect'][3]) / scale
            assert bottom >= 5 and top >= 5, (control, bottom, top)
    # Enlarged UI can trigger native row fitting in the fixed-width QA window.
    # The control must stay compact; pixel checks below still require full content.
    user_scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    if user_scale == 1.0:
        assert abs(width - 120) <= 2, (width, target)
    else:
        assert 114 <= width <= 122, (width, target)
    path = OUT / f'{name}.png'
    qa.cmd('snap', path=str(path), target=query, margin=0)
    with Image.open(path).convert('RGB') as image:
        w, h = image.size
        # Bright neutral pixels identify the film-strip/text, excluding green chrome.
        points = [(x, y) for y in range(int(scale), h-int(scale))
                  for x in range(int(3*scale), w-int(3*scale))
                  if min(image.getpixel((x, y))) > 120
                  and max(image.getpixel((x, y))) - min(image.getpixel((x, y))) < 35]
        assert points, path
        left, right = min(x for x, _ in points), max(x for x, _ in points)
        assert left >= 5*scale and right < w-5*scale, (left, right, w)
        assert abs((left+right+1)/2-w/2) < 3*scale, (left, right, w)
        film = [(x, y) for x, y in points if x < left+16*scale]
        assert len(film) > 20*scale*scale, ('missing film strip', path)
        assert max(y for _, y in film)-min(y for _, y in film) > 9*scale, path
        # The last text island is the small raised V1, separated by a 3px gap.
        occupied = sorted({x for x, _ in points})
        gaps = [(a, b) for a, b in zip(occupied, occupied[1:]) if b-a > 2*scale]
        assert gaps, ('missing version separation', path)
        version_start = gaps[-1][1]
        badge = [(x,y) for x,y in points if x >= version_start]
        main = [(x,y) for x,y in points if left+20*scale < x < version_start-3*scale]
        assert badge and main, ('missing V1 or label', path)
        badge_height = max(y for _,y in badge)-min(y for _,y in badge)+1
        main_height = max(y for _,y in main)-min(y for _,y in main)+1
        assert badge_height < main_height*.85, ('version not smaller', path)
        assert sum(y for _,y in badge)/len(badge) < sum(y for _,y in main)/len(main)-2*scale, ('version not raised', path)
    return {'logical_width': width, 'logical_height': height,
            'row_heights': row_heights, 'scale': scale, 'path': str(path)}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.types, 'MIXAR_OT_director_enter')", timeout=30)
    saved = qa.eval('''
import os
assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA instance'
assert not drv.main_window().scene.mixar_director.is_directing
result = {'scale': bpy.context.preferences.view.ui_scale,
          'tooltips': bpy.context.preferences.view.show_tooltips,
          'zen': drv.main_window().workspace.name == 'Zen Mode'}
''')
    qa.cmd('dismiss_splash')
    results = {}
    try:
        redraw(qa, 'bpy.context.preferences.view.show_tooltips = False')
        for mode, host in (('ai', 'VIEW_3D'), ('pro', 'TOPBAR')):
            qa.click(op=f'MIXAR_OT_set_ui_mode_{mode}')
            qa.wait("(drv.main_window().workspace.name == 'Zen Mode') == " +
                    repr(mode == 'ai'), timeout=12)
            for scale in (1.0, 1.25):
                redraw(qa, f'bpy.context.preferences.view.ui_scale = {scale}')
                label = f'{mode}-{scale}'
                results[label] = qa.step(label, capture, qa, host, label, False)
            redraw(qa, 'bpy.context.preferences.view.ui_scale = 1.0')
            qa.click(area_type=host, region_type='HEADER', op='MIXAR_OT_director_enter')
            qa.wait('drv.main_window().scene.mixar_director.is_directing', timeout=10)
            results[mode+'-active'] = qa.step(mode+'-active', capture,
                                              qa, host, mode+'-active', True)
            qa.click(area_type=host, region_type='HEADER', op='MIXAR_OT_director_finish')
            qa.wait('not drv.main_window().scene.mixar_director.is_directing', timeout=10)
            qa.cmd('snap', path=str(OUT / f'{mode}-full.png'))
        return {'measurements': results, 'backend_calls': 0}
    finally:
        redraw(qa, f"bpy.context.preferences.view.ui_scale = {saved['scale']}\n"
                   f"bpy.context.preferences.view.show_tooltips = {saved['tooltips']}")
        if qa.eval('result=drv.main_window().scene.mixar_director.is_directing'):
            qa.click(op='MIXAR_OT_director_finish')
        qa.click(op='MIXAR_OT_set_ui_mode_ai' if saved['zen'] else 'MIXAR_OT_set_ui_mode_pro')


if __name__ == '__main__':
    run_scenario('cinema_button_e2e', run)
