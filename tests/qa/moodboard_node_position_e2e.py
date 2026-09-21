#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit replay: node-relative layout, clipping, padding and title zoom.

Set QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT. Requires Pillow. Placement
fixtures use eval; panning, zooming and text editing use native events.
Inspect the saved edge captures as well as the state/pixel assertions.
"""

import json

from PIL import Image, ImageChops

from moodboard_drawer_e2e import OUT, SCENE, geometry, require, run_scenario, target, toggle
from moodboard_drawer_tools_e2e import resize
from moodboard_node_layout_e2e import BLOCK, GENERATE, SETTINGS, inside
from moodboard_redesign_e2e import ADD, TEMPLATES


def context(host):
    kind = 'TOOL_PROPS' if host == 'VIEW_3D' else 'WINDOW'
    return f"""
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=={host!r})
region=next(r for r in area.regions if r.type=={kind!r})
node=win.scene.mixie_moodboard_action_nodes[0]
"""


def bounds(qa, host):
    if host == 'VIEW_3D':
        return target(qa, 'moodboard_drawer_panel')['rect']
    return qa.eval(context(host) + """
sidebar=next((r for r in area.regions if r.type=='UI' and r.width>1),None)
result=[region.x,region.y,sidebar.x if sidebar else region.x+region.width,
        region.y+region.height]
""")


def card(qa, host):
    return qa.eval(context(host) + """
a=region.view2d.view_to_region(node.position_x,node.position_y,clip=False)
b=region.view2d.view_to_region(node.position_x+node.width,node.position_y+node.height,clip=False)
result=[a[0]+region.x,a[1]+region.y,b[0]+region.x,b[1]+region.y]
""")


def center_fixture(qa, host, size=False):
    x0, y0, x1, y1 = bounds(qa, host)
    qa.eval(context(host) + f"""
cx,cy={(x0+x1)/2!r},{(y0+y1)/2!r}
if {size!r}:
    a=region.view2d.region_to_view(0,0)
    b=region.view2d.region_to_view(560,440)
    node.width,node.height=b[0]-a[0],b[1]-a[1]
cx,cy=region.view2d.region_to_view(cx-region.x,cy-region.y)
node.position_x,node.position_y=cx-node.width/2,cy-node.height/2
node.prompt='Red dragon over a mountain lake'
area.tag_redraw()
# RNA placement tags a redraw; finish it before capture reads the framebuffer.
bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
result=True
""")


def controls(qa, host):
    region = 'TOOL_PROPS' if host == 'VIEW_3D' else 'WINDOW'
    return [w for w in qa.find(area_type=host, region_type=region, limit=500)['widgets']
            if w.get('block') == BLOCK]


def offsets(qa, host):
    x0, y0, *_ = card(qa, host)
    return {(w.get('op') or w.get('prop')):
            [r-v for r, v in zip(w['layout_rect'], (x0, y0, x0, y0))]
            for w in controls(qa, host) if w.get('op') or w.get('prop')}


def assert_offsets(qa, host, expected):
    current = offsets(qa, host)
    require(current, 'Partially visible card lost every control')
    for key, rect in current.items():
        require(key in expected and all(abs(a-b) <= 2 for a, b in zip(rect, expected[key])),
                f'{host}: {key} reflowed at the canvas edge: {rect} != {expected.get(key)}')
    # Native controls paint beneath the overlapping N-panel; its own region
    # receives input there. The drawer's external tab gutter remains excluded.
    painted = bounds(qa, host) if host == 'VIEW_3D' else qa.eval(context(host) +
        'result=[region.x,region.y,region.x+region.width,region.y+region.height]')
    for widget in controls(qa, host):
        require(inside(widget['rect'], painted), 'Control escaped the painting surface')
    return current


def pan(qa, host, dx, dy):
    x0, y0, x1, y1 = bounds(qa, host)
    start = {'x': round((x0+x1)/2), 'y': round((y0+y1)/2)}
    qa.cmd('drag', **{'from': start, 'to': {'x': start['x']+round(dx),
                                          'y': start['y']+round(dy)},
                     'button': 'MIDDLEMOUSE', 'steps': 14})


def capture(qa, host, name):
    return qa.cmd('snap', path=str(OUT/f'{host}_{name}.png'), area=host)


def edges(qa, host):
    center_fixture(qa, host, size=True)
    original = offsets(qa, host)
    require({SETTINGS, GENERATE, 'prompt'} <= original.keys(), 'Missing baseline controls')
    settings, prompt, generate = original[SETTINGS], original['prompt'], original[GENERATE]
    width = card(qa, host)[2]-card(qa, host)[0]
    require(abs(settings[0] - (width-settings[2])) <= 2, 'Unequal model left/right padding')
    require(abs(settings[0]-prompt[0]) <= 1 and abs(settings[2]-prompt[2]) <= 1,
            'Model and prompt do not share side padding')
    require(abs(generate[1]-settings[0]) <= 1, 'Action bottom padding differs from side padding')
    captures = []
    for edge in ('right', 'left', 'top', 'bottom'):
        center_fixture(qa, host)
        x0, y0, x1, y1 = bounds(qa, host)
        a, b, c, d = card(qa, host)
        dx = x1-c+90 if edge == 'right' else x0-a-90 if edge == 'left' else 0
        dy = y1-d+90 if edge == 'top' else y0-b-90 if edge == 'bottom' else 0
        pan(qa, host, dx, dy)
        assert_offsets(qa, host, original)
        captures.append(capture(qa, host, edge))
        if edge == 'right':
            qa.cmd('set_text', widget={'area_type': host,
                   'region_type': 'TOOL_PROPS' if host=='VIEW_3D' else 'WINDOW',
                   'prop': 'prompt'}, text='Red dragon stays in place', enter=False)
            qa.wait(f"{SCENE}.mixie_moodboard_action_nodes[0].prompt=='Red dragon stays in place'",
                    timeout=4)
            qa.press('ESC')
            assert_offsets(qa, host, original)
    return {'stable_offsets': original, 'edge_captures': captures}


def refined_padding(qa, host):
    center_fixture(qa, host, size=True)
    qa.eval(context(host) + """
a=region.view2d.region_to_view(0,0)
b=region.view2d.region_to_view(400,0)
node.width=b[0]-a[0]
node.prompt_refined=True
node.prompt_pre_refine='Original dragon prompt'
area.tag_redraw()
bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=2)
result=True
""")
    expected=offsets(qa,host)
    require({'MIXIE_OT_refine_prompt','MIXIE_OT_revert_prompt',GENERATE,'prompt'} <= expected.keys(),
            'Revert hid part of a narrow node editor')
    actual_width=card(qa,host)[2]-card(qa,host)[0]
    for rect in expected.values():
        require(rect[0]>=23 and rect[2]<=actual_width-23,
                f'Refined controls lost side padding: {rect}, width={actual_width}')
    capture(qa,host,'refined_padding')
    pan(qa,host,60,0)
    assert_offsets(qa,host,expected)
    qa.eval(context(host)+"node.prompt_refined=False\nresult=True")
    center_fixture(qa,host,size=True)
    return expected


def title_pixels(qa, host, index):
    center_fixture(qa, host)
    node_id = qa.eval(f'result={SCENE}.mixie_moodboard_action_nodes[0].node_id')
    path = OUT/f'{host}_title_{index}.png'
    qa.cmd('snap', path=str(path), target={'surface': 'moodboard_node_title',
                                         'text': node_id, 'area_type': host}, margin=0)
    image = Image.open(path).convert('RGB')
    r, g, b = image.split()
    mask = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v>165 else 0)
    rect = mask.getbbox()
    require(rect is not None, 'Title was not painted')
    return {'ink_width': rect[2]-rect[0], 'ink_height': rect[3]-rect[1],
            'card_width': card(qa, host)[2]-card(qa, host)[0]}


def zoom_titles(qa, host):
    sizes = [title_pixels(qa, host, 0)]
    for index, key in enumerate(('WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELDOWNMOUSE'), 1):
        pan(qa, host, 1, 0)  # Put the pointer in the canvas for the wheel events.
        qa.press(key)
        qa.press(key)
        sizes.append(title_pixels(qa, host, index))
    require(max(s['card_width'] for s in sizes)-min(s['card_width'] for s in sizes) > 100,
            f'Zoom did not change card size: {sizes}')
    require(max(s['ink_height'] for s in sizes)-min(s['ink_height'] for s in sizes) <= 1
            and max(s['ink_width'] for s in sizes)-min(s['ink_width'] for s in sizes) <= 1,
            f'Zoom changed the rendered title font: {sizes}')
    return sizes


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"), 'Use isolated QA')
    qa.cmd('wait_login', timeout=90)
    qa.wait("__import__('mixar.bootstrap.generation_catalog_cache',"
            "fromlist=['is_loaded']).is_loaded()", timeout=45)
    if geometry(qa)['amount'] < .98:
        toggle(qa, 1)
    resize(qa, 850)
    qa.click(op=ADD, text='Video Generation', region_type='TOOL_PROPS')
    results = {}
    for host in ('VIEW_3D', 'MIXIE'):
        if host == 'MIXIE':
            qa.eval("win=drv.main_window()\narea=next(a for a in win.screen.areas if a.type=='VIEW_3D')\n"
                    "area.type='MIXIE'\nresult=True")
            qa.wait("bool(drv.find(area_type='MIXIE',op='"+ADD+"'))", timeout=5)
        results[host] = qa.step(host+'_edge_layout', edges, qa, host)
        results[host]['refined_padding'] = qa.step(host+'_refined_padding', refined_padding, qa, host)
        results[host]['zoom_titles'] = qa.step(host+'_title_zoom', zoom_titles, qa, host)
    # A clean fixture isolates the exact Upscale Video padding shown in the report.
    qa.eval(f'{SCENE}.mixie_moodboard_action_nodes.clear(); result=True')
    qa.click(**TEMPLATES, area_type='MIXIE')
    qa.click(op=ADD, text='Upscale Video', popup=True)
    qa.wait(f"len({SCENE}.mixie_moodboard_action_nodes)==1", timeout=5)
    center_fixture(qa,'MIXIE',size=True)
    capture(qa,'MIXIE','upscale_padding')
    results['upscale'] = qa.step('upscale_edge_padding',edges,qa,'MIXIE')
    require(qa.eval(f"result=all(n.state=='DRAFT' and not n.job_id "
                    f"for n in {SCENE}.mixie_moodboard_action_nodes)"), 'Unexpected generation')
    (OUT/'state-evidence.json').write_text(json.dumps(results, indent=2))
    return {'backend_submissions': 0, 'evidence': results}


if __name__ == '__main__':
    run_scenario('moodboard_node_position_e2e', run)
