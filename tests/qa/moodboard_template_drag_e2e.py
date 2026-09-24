#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native template drag/drop, cancellation and coordinate regression.

Use a fresh isolated QA scene with a live catalog. Set QA_HARNESS,
MIXAR_QA_PORT and QA_SCENARIO_OUT. Inputs come from live native widget bounds;
eval only reads state, switches the editor fixture or emits pointer events.
No Generate action is invoked. Inspect the saved screenshots.
"""

import json
import time

from moodboard_drawer_e2e import (
    OUT, SCENE, geometry, point, require, run_scenario, target, toggle,
)
from moodboard_drawer_tools_e2e import resize
from moodboard_redesign_e2e import ADD, BOARD, KINDS, LABELS, nodes, shortcuts, snapshot


def region_kind(host):
    return 'TOOL_PROPS' if host == 'VIEW_3D' else 'WINDOW'


def canvas_setup(host):
    return f"""
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=={host!r})
region=next(r for r in area.regions if r.type=={region_kind(host)!r})
"""


def destination(qa, host, fx=.5, fy=.5):
    if host == 'VIEW_3D':
        return point(target(qa, 'moodboard_drawer_panel'), fx, fy)
    return qa.eval(canvas_setup(host) + f"""
sidebar=next((r for r in area.regions if r.type=='UI' and r.width>1),None)
right=sidebar.x if sidebar else region.x+region.width
result={{'x':round(region.x+(right-region.x)*{fx}),
         'y':round(region.y+region.height*{fy})}}
""")


def drop_template(qa, host, label, kind, xy):
    before = nodes(qa)
    expected = qa.eval(canvas_setup(host) + f"""
result=list(region.view2d.region_to_view({xy['x']}-region.x,{xy['y']}-region.y))
""")
    qa.cmd('drag', **{'from': {'op': ADD, 'text': label, 'area_type': host,
                               'region_type': region_kind(host)},
                     'to': xy, 'steps': 18})
    qa.wait(f'len({SCENE}.mixie_moodboard_action_nodes)=={len(before)+1}', timeout=5)
    node = nodes(qa)[-1]
    x, y, width, height = node['rect']
    require(node['type'] == kind and node['state'] == 'DRAFT' and not node['job_id'],
            f'Drag submitted a job or created the wrong node: {node}')
    require(abs(x+width/2-expected[0]) < .02 and abs(y+height/2-expected[1]) < .02,
            f'Drop missed its canvas coordinates: {node}, {expected}')
    projected = qa.eval(canvas_setup(host) + f"""
p=region.view2d.view_to_region({x+width/2},{y+height/2},clip=False)
result=[p[0]+region.x,p[1]+region.y]
""")
    require(abs(projected[0]-xy['x']) <= 2 and abs(projected[1]-xy['y']) <= 2,
            f'Drop moved the view away from the release point: {projected}, {xy}')
    return {'node': node['id'], 'release': xy, 'canvas_center': expected}


def cancel_drag(qa, host):
    before = nodes(qa)
    xy = destination(qa, host, .45, .5)
    query = {'op': ADD, 'text': LABELS[0], 'area_type': host,
             'region_type': region_kind(host)}
    qa.eval(f"""
def gesture():
    button=drv.find_one(**{query!r})
    win=button['_win']
    x,y=drv.pick_click_point(button)
    drv.move_to(win,x,y)
    yield .1
    drv._sim(win,type='LEFTMOUSE',value='PRESS',x=x,y=y)
    yield .1
    for i in range(1,13):
        drv.move_to(win,round(x+({xy['x']}-x)*i/12),round(y+({xy['y']}-y)*i/12))
        yield .04
    drv.press(win,'ESC')
    yield .1
    drv._sim(win,type='LEFTMOUSE',value='RELEASE',x={xy['x']},y={xy['y']})
    yield .2
    return True
result=gesture()
""")
    require(nodes(qa) == before, 'Escape created or altered a node')


def outside_drop(qa):
    before = nodes(qa)
    viewport = geometry(qa)['viewport']
    panel = target(qa, 'moodboard_drawer_panel')['rect']
    qa.cmd('drag', **{'from': {'op': ADD, 'text': LABELS[0], 'region_type': 'TOOL_PROPS'},
                     'to': {'x': round((viewport[0]+panel[0])/2),
                            'y': round((viewport[1]+viewport[3])/2)}, 'steps': 18})
    time.sleep(.3)
    require(nodes(qa) == before, 'Dropping into the 3D viewport created a canvas node')


def chrome_drop(qa):
    before = nodes(qa)
    button = qa.find(op=ADD, text=LABELS[1], region_type='TOOL_PROPS')['widgets'][0]
    qa.cmd('drag', **{'from': {'op': ADD, 'text': LABELS[0], 'region_type': 'TOOL_PROPS'},
                     'to': dict(zip(('x', 'y'), button['center'])), 'steps': 18})
    time.sleep(.3)
    require(nodes(qa) == before, 'Dropping on the template strip created a canvas node')


def undo_redo(qa):
    before = nodes(qa)
    modifier = {'oskey': True} if __import__('sys').platform == 'darwin' else {'ctrl': True}
    qa.press('Z', **modifier)
    qa.wait(f'len({SCENE}.mixie_moodboard_action_nodes)=={len(before)-1}', timeout=5)
    qa.press('Z', shift=True, **modifier)
    qa.wait(f'len({SCENE}.mixie_moodboard_action_nodes)=={len(before)}', timeout=5)
    require(nodes(qa) == before, 'Redo did not restore the exact dropped draft')
    qa.press('Z', **modifier)
    qa.wait(f'len({SCENE}.mixie_moodboard_action_nodes)=={len(before)-1}', timeout=5)


def exposed_drop(qa, host):
    canvas = target(qa, 'moodboard_canvas', area_type=host)['rect']
    rail = next(w for w in qa.find(area_type=host, region_type=region_kind(host),
                                  limit=500)['widgets']
                if w.get('block') == 'MIXIE_PT_canvas_tools')
    xy = {'x': rail['center'][0], 'y': canvas[1]+60}
    evidence = drop_template(qa, host, LABELS[0], KINDS[0], xy)
    undo_redo(qa)
    return evidence


def pan_zoom(qa):
    xy = destination(qa, 'VIEW_3D', .65, .7)
    qa.cmd('drag', **{'from': xy, 'to': {'x': xy['x']+85, 'y': xy['y']-55},
                     'button': 'MIDDLEMOUSE', 'steps': 10})
    qa.press('WHEELDOWNMOUSE')
    qa.press('WHEELDOWNMOUSE')


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"),
            'Use an isolated QA app')
    qa.cmd('wait_login', timeout=90)
    qa.wait("__import__('mixar.bootstrap.generation_catalog_cache',"
            "fromlist=['is_loaded']).is_loaded()", timeout=45)
    require(not nodes(qa), 'Use a clean QA scene')
    if geometry(qa)['workspace'] != 'Zen Mode':
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    resize(qa, 850)
    shortcuts(qa)
    original = geometry(qa)
    evidence = []
    for i, (label, kind) in enumerate(zip(LABELS, KINDS)):
        xy = destination(qa, 'VIEW_3D', .3+i*.26, .6-i*.14)
        evidence.append(qa.step('drawer_drop_'+kind, drop_template,
                                qa, 'VIEW_3D', label, kind, xy))
    qa.step('drawer_drag_snapshot', snapshot, qa, '01_drawer_drops')
    qa.step('escape_cancels', cancel_drag, qa, 'VIEW_3D')
    qa.step('outside_drop_cancels', outside_drop, qa)
    qa.step('chrome_drop_cancels', chrome_drop, qa)
    qa.step('pan_and_zoom', pan_zoom, qa)
    evidence.append(qa.step('drop_after_pan_zoom', drop_template, qa, 'VIEW_3D',
                           LABELS[0], KINDS[0], destination(qa, 'VIEW_3D', .57, .55)))
    # Native Undo must remove exactly the dropped template, with no second click action.
    qa.step('undo_redo_drop', undo_redo, qa)
    qa.step('undo_snapshot', snapshot, qa, '02_undo_drop')
    evidence.append(qa.step('drawer_drop_below_toolbar', exposed_drop, qa, 'VIEW_3D'))
    final = geometry(qa)
    require(original['view'] == final['view'] and original['objects'] == final['objects'],
            'Template drags changed the 3D scene')
    qa.eval("win=drv.main_window()\n"
            "area=next(a for a in win.screen.areas if a.type=='VIEW_3D')\n"
            "area.type='MIXIE'\nresult=True")
    qa.wait("bool(drv.find(area_type='MIXIE',op='"+ADD+"'))", timeout=5)
    qa.click(**BOARD, region_type='WINDOW')
    qa.click(op='MIXIE_OT_moodboard_frame', popup=True)
    evidence.append(qa.step('editor_drop', drop_template, qa, 'MIXIE',
                           LABELS[1], KINDS[1], destination(qa, 'MIXIE', .6, .6)))
    evidence.append(qa.step('editor_drop_below_toolbar', exposed_drop, qa, 'MIXIE'))
    qa.step('editor_escape_cancels', cancel_drag, qa, 'MIXIE')
    qa.step('editor_drag_snapshot', snapshot, qa, '03_editor_drop', 'MIXIE')
    result = {'backend_submissions': 0, 'exact_drop_centers': evidence,
              'cancel_and_undo': True, 'both_hosts': True}
    (OUT/'state-evidence.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    run_scenario('moodboard_template_drag_e2e', run)
