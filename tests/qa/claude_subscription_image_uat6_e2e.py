#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real Opus 5.5 image follow-up through UAT6 and native composer.

Requires isolated MIXAR_QA=1 app with in-memory credential store, signed into
UAT6 with Claude Opus 5.5 already configured. No provider/HTTP mocks, generation
jobs or changes to the user's ordinary scene. Also runs on the pre-fix desktop
bundle to prove backend v1 compatibility.
"""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/private/tmp/claude-image-evidence'))
OUT.mkdir(parents=True, exist_ok=True)


def run(qa):
    qa.eval("import os\nfrom mixar.config.config import get_server_url\nfrom mixar.modules.byok.core import credential_state as S,key_store as K\nassert os.environ.get('MIXAR_QA')=='1' and 'uat6.mixar.app' in get_server_url()\ns=S.snapshot()\nassert s['byok_current_provider']=='claude_code' and s['byok_current_model']=='claude-opus-5-5' and s['byok_is_active']\nassert not bpy.context.window_manager.mixie_chat_is_guest\nassert K.save(K.make_record('claude_code',None,model='claude-opus-5-5'))\nresult=True")
    qa.step('wait_authenticated_socket', qa.wait, "bool(__import__('mixar.modules.space_mixie_chat.core.jsonrpc_client',fromlist=['get_jsonrpc_client']).get_jsonrpc_client() and __import__('mixar.modules.space_mixie_chat.core.jsonrpc_client',fromlist=['get_jsonrpc_client']).get_jsonrpc_client().is_connected)", timeout=120)
    for window in {w['window'] for w in qa.find(popup=True)['widgets']}:
        qa.press('ESC', window=window)
    qa.eval("result=str(bpy.ops.mixar.open_mixie())")
    qa.wait("bool(drv.find(prop='mixie_chat_input',area_type='AGENT_BUBBLE'))", timeout=10)
    prompt = ('Inspect the existing default cube visually. Call render_viewport with quality fast, '
              'view hero, focus_objects [Cube], width 512 and height 512. Then explicitly call '
              'view_image on the returned image reference, and describe what you actually see '
              'in one short sentence. Do not modify the scene, generate assets or spawn workers.')
    qa.step('send_image_inspection', qa.cmd, 'set_text', widget={
        'prop': 'mixie_chat_input', 'area_type': 'AGENT_BUBBLE'}, text=prompt, enter=True)
    turn = qa.step('real_opus_image_turn', qa.cmd, 'wait_turn', timeout=300, accept_gate=False)
    answer = turn['last_agent_text']
    assert turn['terminal'] == 'idle' and 'cube' in answer.lower(), turn
    assert 'could not continue' not in answer.lower() and 'try again' not in answer.lower(), turn
    state = qa.eval("scene=drv.main_window().scene\nassert scene.objects.get('Cube') is not None\nresult={'session_id':scene.mixie_session_id,'objects':len(scene.objects),'provider':bpy.context.window_manager.byok_current_provider,'model':bpy.context.window_manager.byok_current_model}")
    qa.cmd('snap', path=str(OUT / 'opus-image-chat.png'), target={
        'prop': 'mixie_chat_input', 'area_type': 'AGENT_BUBBLE'}, margin=8000)
    return {'turn': turn, 'state': state, 'snaps': [str(OUT / 'opus-image-chat.png')]}


if __name__ == '__main__':
    run_scenario('claude_subscription_image_uat6_e2e', run)
