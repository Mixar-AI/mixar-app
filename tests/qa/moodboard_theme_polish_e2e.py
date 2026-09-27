#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit sketch/default and node styling replay in an isolated QA app.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Inspect captured PNGs.
Generate and Refine are never submitted; refined state is a local fixture.
"""
import os
from pathlib import Path
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from moodboard_annotations_e2e import set_mode, draw, strokes

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-theme-polish'))
BLOCK = 'moodboard_floating_node_controls'
OPS = {'MIXIE_OT_refine_prompt', 'MIXIE_OT_revert_prompt', 'MIXIE_OT_moodboard_run_action_node'}


def snap(qa, name, query):
    path = OUT / f'{name}.png'
    for _ in range(2):
        qa.cmd('snap', path=str(path), target=query, margin=12)
        time.sleep(.3)
    return path


def check_node(qa, host, node_id, width, refined):
    region = 'TOOL_PROPS' if host == 'VIEW_3D' else 'WINDOW'
    qa.eval(f"""
w=drv.main_window()
a=next(a for a in w.screen.areas if a.type=={host!r})
r=next(r for r in a.regions if r.type=={region!r})
n=next(n for n in w.scene.mixie_moodboard_action_nodes if n.node_id=={node_id!r})
b=drv.find_one(surface='moodboard_canvas',area_type={host!r})['rect']
x=(b[0]+b[2]-{width})/2-r.x
y=(b[1]+b[3]-340)/2-r.y
p=r.view2d.region_to_view(x,y)
q=r.view2d.region_to_view(x+{width},y+340)
n.position_x,n.position_y=p
n.width=q[0]-p[0]
n.height=q[1]-p[1]
n.prompt_refined={refined!r}
a.tag_redraw()
result=True
""")
    qa.wait(f"bool(drv.find(area_type={host!r},prop='prompt'))", timeout=10)
    time.sleep(.3)
    widgets = qa.eval(f"result=[w for w in drv.find(area_type={host!r},region_type={region!r}) "
                      f"if w.get('block')=={BLOCK!r}]")
    prompt = next(w['rect'] for w in widgets if w.get('prop') == 'prompt')
    actions = [w['rect'] for w in widgets if w.get('op') in OPS]
    assert len(actions) == (3 if refined else 2), widgets
    left, right = min(r[0] for r in actions), max(r[2] for r in actions)
    assert abs((left+right)-(prompt[0]+prompt[2])) <= 2, (prompt, actions)
    assert left >= prompt[0]-1 and right <= prompt[2]+1, (prompt, actions)
    ordered = sorted(actions)
    assert all(a[2] <= b[0] for a,b in zip(ordered, ordered[1:])), actions
    snap(qa, f'{host}-{width}-refined-{refined}', {'surface':'moodboard_node','text':node_id})
    return {'host':host,'width':width,'refined':refined,'actions':actions}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval("""
import os
assert os.environ.get('MIXAR_QA')=='1'
from mixar.modules.onboarding.core.tour import session
if session.current(): session.current().stop('theme-polish-qa')
bpy.context.preferences.view.show_tooltips=False
bpy.ops.mixar.apply_forest_theme()
drv.main_window().workspace=bpy.data.workspaces['Zen Mode']
result=True
""")
    qa.click(surface='moodboard_drawer_grip')
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .99',timeout=10)
    color = qa.eval('result=list(drv.main_window().scene.mixie_edit_tool_state.annotation_color)')
    assert [round(c*255) for c in color] == [105,111,108,255], color
    set_mode(qa, True)
    draw(qa)
    assert [round(c*255) for c in strokes(qa)[-1]['color']] == [105,111,108,255]
    set_mode(qa, False)
    path = snap(qa, 'neutral-gray-sketch', {'surface':'moodboard_drawer_panel'})
    with Image.open(path).convert('RGB') as image:
        hits=sum(n for n,c in image.getcolors(image.width*image.height)
                 if all(abs(a-b)<=1 for a,b in zip(c,(105,111,108))))
        assert hits > 30, 'Gray sketch not visible'
    qa.eval('drv.main_window().scene.mixie_moodboard_annotations.clear(); result=True')
    node_id = qa.eval("from mixar.modules.moodboard.core.node_graph import create_connected_action\n"
                      "n=create_connected_action(drv.main_window().scene,'IMAGE_GEN'); result=n.node_id")
    checks=[]
    for host in ('VIEW_3D','MIXIE'):
        if host=='MIXIE':
            qa.click(surface='moodboard_drawer_grip')
            qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount < .01',timeout=10)
            qa.eval("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').type='MIXIE'; result=True")
        for width, refined in ((430,False),(430,True),(390,True)):
            checks.append(qa.step(f'{host}-{width}-{refined}',check_node,qa,host,node_id,width,refined))
    return {'sketch':'#696F6C','layouts':checks,'paid_requests':0}


if __name__=='__main__':
    run_scenario('moodboard_theme_polish',run)
