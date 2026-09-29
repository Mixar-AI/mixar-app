#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Enter in a canvas node prompt runs that node, in BOTH canvas hosts.

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4791 python3 tests/qa/moodboard_node_prompt_enter_e2e.py
Requires a fresh isolated Dev app. ``run_action_node`` is replaced by a spy for
the run, so nothing is queued and no credits are spent. Shift+Enter must add a
line without submitting; plain Enter must submit the whole prompt through the
node's own run operator. The Zen drawer (a View3D TOOL_PROPS region) used to
only confirm the text. Inspect the captured PNGs beside the state asserts.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-node-prompt-enter'))
SPY = "bpy.app.driver_namespace['node_prompt_enter_calls']"


def place(qa, host, node_id):
    """Centre the node in the host's canvas, large enough for its prompt."""
    region = 'TOOL_PROPS' if host == 'VIEW_3D' else 'WINDOW'
    qa.eval(f"""
w=drv.main_window()
a=next(a for a in w.screen.areas if a.type=={host!r})
r=next(r for r in a.regions if r.type=={region!r})
n=next(n for n in w.scene.mixie_moodboard_action_nodes if n.node_id=={node_id!r})
b=drv.find_one(surface='moodboard_canvas',area_type={host!r})['rect']
x=(b[0]+b[2]-430)/2-r.x
y=(b[1]+b[3]-340)/2-r.y
p=r.view2d.region_to_view(x,y)
q=r.view2d.region_to_view(x+430,y+340)
n.position_x,n.position_y=p
n.width=q[0]-p[0]
n.height=q[1]-p[1]
n.prompt=''
n.state='DRAFT'
a.tag_redraw()
result=True
""")
    qa.wait(f"bool(drv.find(area_type={host!r},prop='prompt'))", timeout=10)
    time.sleep(.3)


def enter_submits(qa, host, node_id):
    place(qa, host, node_id)
    before = qa.eval(f'result=len({SPY})')
    qa.click(area_type=host, prop='prompt')
    qa.cmd('type', text='a red fox')
    qa.press('RET', shift=True)
    qa.cmd('type', text='at dusk')
    time.sleep(.2)
    assert qa.eval(f'result=len({SPY})') == before, 'Shift+Enter submitted the node'
    qa.cmd('snap', path=str(OUT / f'{host}-typed.png'),
           target={'surface': 'moodboard_node', 'text': node_id}, margin=12)
    qa.press('RET')
    qa.wait(f'len({SPY})=={before + 1}', timeout=5)
    call = qa.eval(f'result={SPY}[-1]')
    assert call == {'node_id': node_id, 'prompt': 'a red fox\nat dusk'}, call
    qa.cmd('snap', path=str(OUT / f'{host}-submitted.png'),
           target={'surface': 'moodboard_node', 'text': node_id}, margin=12)
    return {'host': host, 'call': call}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval(f"""
import os, types
assert os.environ.get('MIXAR_QA')=='1'
from mixar.modules.onboarding.core.tour import session
if session.current(): session.current().stop('node-prompt-enter-qa')
bpy.context.preferences.view.show_tooltips=False
from mixar.modules.moodboard.core import node_execution
bpy.app.driver_namespace['node_prompt_enter_real']=node_execution.run_action_node
{SPY}=[]
def _spy(context, node, operator):
    {SPY}.append({{'node_id':node.node_id,'prompt':node.prompt}})
    return types.SimpleNamespace(job_id='qa-spy')
node_execution.run_action_node=_spy
drv.main_window().workspace=bpy.data.workspaces['Zen Mode']
result=True
""")
    try:
        qa.click(surface='moodboard_drawer_grip')
        qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .99', timeout=10)
        node_id = qa.eval(
            "from mixar.modules.moodboard.core.node_graph import create_connected_action\n"
            "n=create_connected_action(drv.main_window().scene,'IMAGE_GEN'); result=n.node_id")
        results = [qa.step('drawer_enter_submits', enter_submits, qa, 'VIEW_3D', node_id)]
        qa.click(surface='moodboard_drawer_grip')
        qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount < .01', timeout=10)
        qa.eval("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')"
                ".type='MIXIE'; result=True")
        results.append(qa.step('editor_enter_submits', enter_submits, qa, 'MIXIE', node_id))
        return {'passed': True, 'hosts': results, 'paid_requests': 0}
    finally:
        qa.eval("""
from mixar.modules.moodboard.core import node_execution
real=bpy.app.driver_namespace.pop('node_prompt_enter_real', None)
if real: node_execution.run_action_node=real
result=True
""")


if __name__ == '__main__':
    run_scenario('moodboard_node_prompt_enter', run)
