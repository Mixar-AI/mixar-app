#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real UAT6 + Claude subscription + scene mutation, no inference mocks.

Requires an isolated MIXAR_QA=1 app using UAT6 and Claude subscription already
activated. Uses several small real Claude calls; no paid generation. The
single QA-named cube remains in the isolated scene as visual evidence.
QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4796 python3 <this-file>
"""
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT=Path(os.environ.get('QA_SCENARIO_OUT','/private/tmp/claude-provider-evidence'))
OUT.mkdir(parents=True,exist_ok=True)


def run(qa):
    name='QA_CLAUDE_UAT6_'+uuid.uuid4().hex[:6]
    qa.eval("import os\nfrom mixar.config.config import get_server_url\nfrom mixar.modules.byok.core import credential_state as S\nassert os.environ.get('MIXAR_QA')=='1'\nassert 'uat6.mixar.app' in get_server_url()\nassert S.snapshot()['byok_current_provider']=='claude_code' and S.snapshot()['byok_is_active']\nresult=True")
    for window in {w['window'] for w in qa.find(popup=True)['widgets']}:
        qa.press('ESC',window=window)
    qa.eval("result=str(bpy.ops.mixar.open_mixie())")
    qa.wait("bool(drv.find(prop='mixie_chat_input',area_type='AGENT_BUBBLE'))",timeout=10)
    prompt=f'Create one plain cube named {name} at (3, 0, 0), inspect its dimensions, and confirm. Use direct script execution; do not generate assets or spawn workers.'
    qa.step('send_through_native_composer',qa.cmd,'set_text',widget={'prop':'mixie_chat_input','area_type':'AGENT_BUBBLE'},text=prompt,enter=True)
    turn=qa.step('real_claude_turn',qa.cmd,'wait_turn',timeout=240,accept_gate=False)
    state=qa.eval(f"scene=drv.main_window().scene\nobj=scene.objects.get({name!r})\nassert obj is not None,'Claude did not create the requested cube'\nassert all(abs(v-w)<0.001 for v,w in zip(obj.location,(3,0,0))),list(obj.location)\nassert all(abs(v-2)<0.001 for v in obj.dimensions),list(obj.dimensions)\nresult={{'name':obj.name,'location':list(obj.location),'dimensions':list(obj.dimensions),'provider':bpy.context.window_manager.byok_current_provider}}")
    qa.eval(f"win=drv.main_window()\narea=next(a for a in win.screen.areas if a.type=='VIEW_3D')\nregion=next(r for r in area.regions if r.type=='WINDOW')\nobj=win.scene.objects[{name!r}]\nfor o in win.scene.objects:o.select_set(False)\nobj.select_set(True);win.view_layer.objects.active=obj\nwith bpy.context.temp_override(window=win,area=area,region=region):\n old_smooth=bpy.context.preferences.view.smooth_view\n bpy.context.preferences.view.smooth_view=0\n bpy.ops.view3d.view_selected(use_all_regions=False)\n bpy.context.preferences.view.smooth_view=old_smooth\n area.spaces.active.region_3d.view_distance*=1.6\nresult=True")
    qa.snap(str(OUT/'live-cube.png'))
    bubble=qa.find(prop='mixie_chat_input',area_type='AGENT_BUBBLE')['widgets'][0]
    qa.cmd('snap',path=str(OUT/'live-chat.png'),target={'prop':'mixie_chat_input','area_type':'AGENT_BUBBLE'},margin=8000)
    return {'turn':turn,'state':state,'snaps':[str(OUT/'live-cube.png'),str(OUT/'live-chat.png')]}


if __name__=='__main__':
    run_scenario('claude_subscription_uat6_e2e',run)
