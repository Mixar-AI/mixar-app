#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Library reflow, native clicks and rendered-label QA.

Run on a fresh isolated app with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT.
Fixtures are local .blend assets and generated-media records, not paid jobs.
Every click and assertion uses native button rectangles or real RNA state.
"""
import json
import os
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from library_responsive_fixture import install

WM = 'bpy.context.window_manager'
BUBBLE = {'area_type': 'AGENT_BUBBLE', 'text': 'Agent chat'}
LIBRARY = {'area_type': 'AGENT_BUBBLE', 'text': 'Your generations and connected asset libraries'}
ADD = {'area_type': 'AGENT_BUBBLE', 'op': 'MIXAR_OT_generations_add_asset'}
FOLDER = {'area_type': 'AGENT_BUBBLE', 'op': 'MIXAR_OT_generations_open_folder'}
SORT = {'area_type': 'AGENT_BUBBLE', 'text': 'Newest first / oldest first'}
FILTERS = ('ALL', 'THREE_D', 'IMAGE', 'VIDEO', 'SPLAT')


def settle(qa):
    qa.eval('def wait():\n    yield .4\n    return True\nresult=wait()')


def size(qa, width, height):
    qa.eval(f'w=drv.find_one(**{BUBBLE!r})["_win"]\n'
            'with bpy.context.temp_override(window=w):\n'
            f'    bpy.ops.mixar.bubble_set_size(width={width},height={height})\nresult=True')
    settle(qa)


def hit(qa, query):
    return qa.find(**query)['widgets'][0]


def disjoint(a, b):
    return a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def choose(qa, surface, value, prop):
    qa.click(surface=surface, value=value)
    qa.wait(f'{WM}.{prop}=={value!r}', timeout=5)
    settle(qa)
    assert hit(qa, {'surface': surface, 'value': value})['sel']


def capture(qa, out, name, annotate=False):
    path = out / f'{name}.png'
    args = {'path': str(path), 'target': BUBBLE, 'margin': 4000}
    if annotate:
        args['annotate'] = {'surface': 'library_filter'}
    result = qa.cmd('snap', **args)
    with Image.open(path) as image:
        assert min(image.size) > 100, image.size
        assert max(image.convert('RGB').getextrema()[0]) > 120, 'Blank app capture'
    return result


def action_ink(path, rect):
    """Measure the white primary-action glyphs, excluding its green fill."""
    with Image.open(path).convert('RGB') as image:
        x0,y0,x1,y1 = map(int, rect)
        crop = image.crop((x0, image.height-y1, x1, image.height-y0))
        points = [(x,y) for y in range(crop.height) for x in range(crop.width)
                  if min(crop.getpixel((x,y))) > 165
                  and max(crop.getpixel((x,y)))-min(crop.getpixel((x,y))) < 35]
        assert points, 'Primary action label did not render'
        xs,ys = zip(*points)
        assert min(xs) >= 2 and max(xs) < crop.width-2, 'Action label clips horizontally'
        assert min(ys) >= 2 and max(ys) < crop.height-2, 'Action label clips vertically'
        return [max(xs)-min(xs)+1, max(ys)-min(ys)+1]


def assert_source_label(path, rect):
    """An inactive source has no dot: bright interior pixels must be its label."""
    with Image.open(path).convert('RGB') as image:
        x0,y0,x1,y1 = map(int,rect)
        crop = image.crop((x0+5,image.height-y1+5,x1-5,image.height-y0-5))
        ink = sum(min(crop.getpixel((x,y))) > 65
                  for y in range(crop.height) for x in range(crop.width))
        assert ink > 100, 'AI generations label vanished during text fitting'


def layout(qa, out, name, selected):
    chips = [hit(qa, {'surface': 'library_filter', 'value': value}) for value in FILTERS]
    chip_rects = [c['rect'] for c in chips]
    sort = hit(qa, SORT)['rect']
    for i,a in enumerate(chip_rects):
        assert disjoint(a,sort), (a,sort)
        for b in chip_rects[i+1:]:
            assert disjoint(a,b), (a,b)
    tiles = qa.find(surface='library_tile')['widgets']
    assert tiles, 'No visible asset tiles after resize'
    top = max(t['rect'][3] for t in tiles)
    columns = sum(abs(t['rect'][3]-top) <= 1 for t in tiles)
    assert 1 <= columns <= 4, columns
    assert top <= min(r[1] for r in chip_rects), 'Grid overlaps filters'
    primary, secondary = hit(qa, ADD)['rect'], hit(qa, FOLDER)['rect']
    assert disjoint(primary, secondary), (primary,secondary)
    assert all(disjoint(t['rect'], primary) for t in tiles)
    bounds = qa.eval(f'w=drv.find_one(**{BUBBLE!r})["_win"]; '
                     'result=[max(a.x+a.width for a in w.screen.areas),'
                     'max(a.y+a.height for a in w.screen.areas)]')
    for r in chip_rects + [sort,primary,secondary]:
        assert 0 <= r[0] < r[2] <= bounds[0] and 0 <= r[1] < r[3] <= bounds[1], (bounds,r)
    assert qa.eval(f'result={WM}.mixar_generations_selected') == selected
    capture(qa,out,name)
    source = hit(qa, {'surface': 'library_source_kind', 'value': 'AI'})['rect']
    assert_source_label(out / f'{name}.png', source)
    ink = action_ink(out / f'{name}.png', primary)
    snapshot = {'columns': columns, 'chip_rows': len(set(r[3] for r in chip_rects)),
                'stacked_actions': abs(primary[1]-secondary[1]) > 1,
                'action_ink': ink, 'filters': chip_rects, 'sort': sort,
                'primary': primary, 'secondary': secondary,
                'tiles': [t['rect'] for t in tiles], 'bounds': bounds}
    (out / f'{name}-geometry.json').write_text(json.dumps(snapshot,indent=2)+'\n')
    return snapshot


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/library-responsive-qa')).resolve()
    out.mkdir(parents=True,exist_ok=True)
    qa.wait(f"hasattr({WM},'mixar_generations_filter')",timeout=30)
    qa.step('local_objects_and_media_fixture',install,qa,out)
    qa.step('open_library_through_tab',qa.click,**LIBRARY)
    qa.wait(f"{WM}.mixar_bubble_tab=='GENERATIONS'",timeout=5)
    size(qa,678,500)
    qa.wait("len(drv.find(surface='library_tile')) >= 4",timeout=30)
    qa.click(surface='library_tile',text='/QA Asset 00',contains=True)
    selected = qa.eval(f'result={WM}.mixar_generations_selected')
    assert selected.endswith('/QA Asset 00'), selected
    saved_scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    saved_points = qa.eval('result=bpy.context.preferences.ui_styles[0].widget.points')
    metrics = {}
    try:
        qa.eval('bpy.context.preferences.view.ui_scale=1.0; '
                'bpy.context.preferences.ui_styles[0].widget.points=12; result=True')
        for width,height in ((1100,500),(678,407),(560,500),(480,500),(400,500),(678,300)):
            size(qa,width,height)
            name = f'layout-{width}x{height}'
            metrics[name] = qa.step(name,layout,qa,out,name,selected)
        assert metrics['layout-1100x500']['columns'] > metrics['layout-480x500']['columns']
        assert any(m['chip_rows'] > 1 for m in metrics.values())
        assert metrics['layout-400x500']['stacked_actions'], 'Narrow actions did not stack'
        assert any(not m['stacked_actions'] for m in metrics.values())
        widths = [m['action_ink'][0] for m in metrics.values()]
        assert max(widths)-min(widths) <= 1, 'Resize changed/clipped the native-size action label'
        qa.step('columns_wrap_and_actions_reflow_without_shrinking_text',lambda: True)
        for scale,points in ((1.25,12),(1.0,15)):
            qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; '
                    f'bpy.context.preferences.ui_styles[0].widget.points={points}; result=True')
            size(qa,678,540)
            name = f'font-{points}-scale-{scale}'
            metrics[name] = qa.step(name,layout,qa,out,name,selected)
            assert metrics[name]['action_ink'][0] > widths[0]*1.15
        qa.eval('bpy.context.preferences.view.ui_scale=1.0; '
                'bpy.context.preferences.ui_styles[0].widget.points=12; result=True')
        size(qa,400,500)
        capture(qa,out,'narrow-annotated',annotate=True)

        def filtering():
            for value in FILTERS:
                choose(qa,'library_filter',value,'mixar_generations_filter')
                tiles = qa.find(surface='library_tile')['widgets']
                assert bool(tiles) == (value in ('ALL','THREE_D')), (value,tiles)
                assert qa.eval(f'result={WM}.mixar_generations_selected') == selected
            capture(qa,out,'empty-filter')
            choose(qa,'library_filter','ALL','mixar_generations_filter')
        qa.step('every_wrapped_filter_click_changes_state_and_recovers',filtering)

        def append():
            qa.click(**ADD)
            qa.wait("bpy.data.objects.get('QA Asset 00') is not None",timeout=5)
            assert qa.eval("result='QA Asset 00' in drv.main_window().scene.objects")
        qa.step('stacked_add_to_scene_dispatches_selected_asset',append)

        def media():
            choose(qa,'library_source_kind','AI','mixar_generations_source')
            choose(qa,'library_filter','IMAGE','mixar_generations_filter')
            qa.wait("len(drv.find(surface='library_tile')) == 3",timeout=5)
            before = [t['value'] for t in qa.find(surface='library_tile')['widgets']]
            qa.click(**SORT)
            qa.wait(f"{WM}.mixar_generations_sort=='OLDEST'",timeout=5)
            settle(qa)
            after = [t['value'] for t in qa.find(surface='library_tile')['widgets']]
            assert before == list(reversed(after)), (before,after)
            qa.click(surface='library_tile',value='media:QA Generated Image 1')
            qa.click(area_type='AGENT_BUBBLE',op='MIXAR_OT_generations_select_media')
            chosen = qa.eval('result=[i.image.name for i in drv.main_window().scene.mixie_moodboard_images '
                             'if i.selected and i.image]')
            assert chosen == ['QA Generated Image 1'], chosen
            capture(qa,out,'selected-media')
        qa.step('source_sort_and_select_on_board_use_native_clicks',media)
        summary = {name: {k: m[k] for k in ('columns','chip_rows','stacked_actions','action_ink')}
                   for name,m in metrics.items()}
        return {'layouts':summary,'paid_requests':0,'screenshots':str(out)}
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved_scale}; '
                f'bpy.context.preferences.ui_styles[0].widget.points={saved_points}; result=True')


if __name__ == '__main__':
    run_scenario('library_responsive_e2e',run)
