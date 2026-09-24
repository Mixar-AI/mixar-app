#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit native Moodboard editor regression with an overlapping sidebar.

Run after launching a clean isolated QA app:
    QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/moodboard_editor_bounds_e2e.py
"""

import json
import os
from pathlib import Path

os.environ.setdefault("QA_SCENARIO_OUT", str(
    Path(__file__).resolve().parents[2] / "build/qa/moodboard-editor-bounds"))

from moodboard_node_layout_e2e import (  # noqa: E402
    BLOCK, GENERATE, OUT, QA, SCENE, inside, overlaps, require, run_scenario,
)

SETUP = """
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='MIXIE')
region=next(r for r in area.regions if r.type=='WINDOW')
sidebar=next(r for r in area.regions if r.type=='UI')
"""


def check(qa):
    bounds = qa.eval(SETUP + """
rect=lambda r:[r.x,r.y,r.x+r.width,r.y+r.height]
result={'canvas':rect(region),'sidebar':rect(sidebar)}
""")
    require(overlaps(bounds['canvas'], bounds['sidebar']),
            'Fixture did not expose an overlapping sidebar')
    items = [w for w in qa.find(area_type='MIXIE', region_type='WINDOW',
                               limit=500)['widgets'] if w.get('block') == BLOCK]
    require(any(w.get('op') == GENERATE for w in items), 'Generate is unreachable')
    require(any(w.get('prop') == 'prompt' for w in items), 'Prompt is unreachable')
    for item in items:
        require(inside(item['rect'], bounds['canvas']), f'Control outside canvas: {item}')
        require(not overlaps(item['rect'], bounds['sidebar']),
                f'Control hidden by sidebar: {item}')
    return {'bounds': bounds, 'controls': items}


def run(qa: QA):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"),
            'Use an isolated QA instance')
    qa.cmd('wait_login', timeout=90)
    qa.wait("__import__('mixar.bootstrap.generation_catalog_cache',"
            "fromlist=['is_loaded']).is_loaded()", timeout=45)
    require(qa.eval(f'result=not {SCENE}.mixie_moodboard_action_nodes'),
            'Use a clean QA scene')
    qa.eval("bpy.context.preferences.system.use_region_overlap=True\n"
            "win=drv.main_window()\n"
            "area=max((a for a in win.screen.areas if a.type in {'VIEW_3D','MIXIE'}),"
            "key=lambda a:a.width*a.height)\narea.type='MIXIE'")
    qa.wait("bool(drv.find(area_type='MIXIE',surface='panel_tab'))", timeout=10)
    if not qa.find(area_type='MIXIE', region_type='UI', prop='prompt')['total']:
        qa.click(area_type='MIXIE', surface='panel_tab', text='Image Gen')
    qa.wait("bool(drv.find(area_type='MIXIE',region_type='UI',prop='prompt'))", timeout=15)
    node_id = qa.eval(SETUP + """
from mixar.modules.moodboard.core.node_graph import create_connected_action
node=create_connected_action(win.scene,'IMAGE_GEN')
# Intentionally let the right edge of the card sit behind the sidebar.
right=min(region.x+region.width,sidebar.x)-region.x
bottom=region.height*.4
lo=region.view2d.region_to_view(right-430,bottom)
hi=region.view2d.region_to_view(right+50,bottom+360)
node.position_x,node.position_y=lo
node.width,node.height=hi[0]-lo[0],hi[1]-lo[1]
area.tag_redraw()
result=node.node_id
""")
    qa.wait("bool(drv.find(area_type='MIXIE',region_type='WINDOW',prop='prompt'))", timeout=5)
    evidence = qa.step('controls_clear_sidebar', check, qa)
    qa.cmd('snap', path=str(OUT / '01_sidebar_bounds.png'), area='MIXIE')
    qa.cmd('set_text', widget={'area_type': 'MIXIE', 'region_type': 'WINDOW',
                               'prop': 'prompt'}, text='A local layout check', enter=False)
    qa.wait(f"any(n.node_id=={node_id!r} and n.prompt=='A local layout check' "
            f"for n in {SCENE}.mixie_moodboard_action_nodes)", timeout=5)
    require(qa.eval(f"result=all(n.state=='DRAFT' for n in {SCENE}.mixie_moodboard_action_nodes)"),
            'Editing the prompt submitted a generation')
    # Commit by clicking known empty canvas, then revisit the node. Enter is
    # deliberately avoided because it is the generation shortcut.
    x0, y0, x1, y1 = evidence['bounds']['canvas']
    scale = qa.eval('result=bpy.context.preferences.system.ui_scale')
    qa.cmd('click_xy', x=round(x0+100*scale), y=round(y0+80*scale))
    qa.click(area_type='MIXIE', surface='moodboard_node', text=node_id)
    qa.step('edited_controls_clear_sidebar', check, qa)
    qa.cmd('snap', path=str(OUT / '02_edited_prompt.png'), area='MIXIE')
    result = {'credits_spent': 0, 'node_id': node_id, 'evidence': evidence}
    (OUT / 'state-evidence.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    run_scenario('moodboard_editor_bounds_e2e', run)
