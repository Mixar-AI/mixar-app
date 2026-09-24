#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real local agent QA: question, typed answer, scene edit, reconnect and Stop.

Requires running QA app + localhost:8000 with configured provider. Uses about
four model turns; no generation jobs. Creates one named cube in the QA scene.
QA_HARNESS=/path/to/mixar-qa-harness QA_SCENARIO_OUT=/tmp/ws-qa \
    python3 tests/qa/agent_websocket_e2e.py
Read the saved screenshots as well as the verdict.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario

SCENE = 'drv.main_window().scene'
CORE = 'mixar.modules.space_mixie_chat.core'
OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/ws-qa'))


def show(qa):
    if qa.find(surface='pill_cat')['total']:
        qa.click(surface='pill_cat')
    else:
        qa.open_chat()
    time.sleep(.4)


def snap(qa, name):
    show(qa)
    qa.cmd('snap', path=str(OUT / (name + '.png')),
           target={'prop': 'mixie_chat_input', 'area_type': 'AGENT_BUBBLE'}, margin=1500)


def drop(qa):
    qa.eval(f'from {CORE}.jsonrpc_client import get_jsonrpc_client\n'
            'get_jsonrpc_client()._ws.close()\nresult = True')
    qa.wait(f'__import__("{CORE}.jsonrpc_client", fromlist=["get_jsonrpc_client"])'
            '.get_jsonrpc_client().is_connected', timeout=45)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.cmd('wait_login', timeout=90)
    qa.wait(f'{SCENE}.mixie_chat_state == "IDLE"', timeout=45)
    endpoint = qa.eval('from mixar.config.config import get_config\nresult = get_config().get("backend_url")')
    if endpoint not in ('http://localhost:8000', 'http://127.0.0.1:8000'):
        raise ScenarioFail(f'Expected local backend, got {endpoint}')
    name = os.environ.get('QA_WS_EXISTING_CUBE') or 'QA_WS_' + str(int(time.time()))
    if not os.environ.get('QA_WS_EXISTING_CUBE'):
        show(qa)
        qa.chat_send('Before making any scene changes, use ask_user with choice buttons to ask '
                     'whether I want a red cube or a blue sphere. Wait for my answer.')
        qa.wait(f'{SCENE}.mixie_chat_state == "AWAITING_INPUT"', timeout=180)
        snap(qa, 'question')
        drop(qa)
        qa.wait(f'{SCENE}.mixie_chat_state == "AWAITING_INPUT"', timeout=30)
        show(qa)
        qa.chat_send(f'Red cube. Create it at X=3 and name it {name}. Do not ask follow-up questions.')
        qa.wait(f'bpy.data.objects.get({name!r}) is not None and {SCENE}.mixie_chat_state == "IDLE"', timeout=240)
    cube = qa.eval(f'ob = bpy.data.objects[{name!r}]\nresult = {{"location": list(ob.matrix_world.translation), '
                   '"materials": [slot.material.name for slot in ob.material_slots if slot.material]}')
    if abs(cube['location'][0] - 3) > .01 or not cube['materials']:
        raise ScenarioFail(f'Cube result mismatch: {cube}')
    snap(qa, 'scene-result-chat')
    qa.snap(str(OUT / 'scene-result.png'))

    # Drop after rendered payloads have advanced: this must exercise attach.
    # Some providers batch prose until completion, so use the actual applied cursor.
    before = qa.eval(f'result = len({SCENE}.mixie_chat_messages)')
    show(qa)
    qa.chat_send('Write 60 numbered practical lighting tips, about one sentence each. '
                 'Do not change the scene or ask questions. End with WS_REPLAY_DONE.')
    qa.wait(f'{SCENE}.mixie_chat_state == "BUSY" and any(t.cursor >= 1 and not t.complete '
            f'for t in __import__("{CORE}.turn_events", fromlist=["_turns"])._turns.values())',
            timeout=60)
    drop(qa)
    qa.wait(f'{SCENE}.mixie_chat_state == "IDLE" and any("WS_REPLAY_DONE" in m.content '
            f'for m in list({SCENE}.mixie_chat_messages)[{before}:])', timeout=240)
    texts = qa.eval(f'result = [m.content for m in list({SCENE}.mixie_chat_messages)[{before}:] if m.sender == "AGENT"]')
    if sum(t.count('WS_REPLAY_DONE') for t in texts) != 1:
        raise ScenarioFail('Replay duplicated the final response')
    snap(qa, 'replayed-response')

    show(qa)
    qa.chat_send('Explain 200 different material design ideas in numbered paragraphs. No scene changes.')
    qa.wait(f'{SCENE}.mixie_chat_state == "BUSY"', timeout=60)
    show(qa)
    qa.click(op='MIXIE_CHAT_OT_abort_session')
    qa.wait(f'{SCENE}.mixie_chat_state == "IDLE" and not {SCENE}.mixie_run_open', timeout=45)
    snap(qa, 'cancelled')
    # Settings no longer ride this socket -- BYOK and the model catalog are HTTP
    # (see tests/qa/byok_http_e2e.py). The backend still registers the commands
    # for older clients, but probing them here would assert a path this client
    # does not take. What stays is the recovery surface, which is socket-only.
    qa.eval(f'from mixar.modules.common.agent_rpc.client import call\n'
            f'drv.ws_checks = {{}}\nsid = {SCENE}.mixie_session_id\n'
            "call('agent.status', {'session_ids': [sid]}, lambda value: drv.ws_checks.update(status=value))\n"
            'result = True')
    qa.wait("any(t.get('status') == 'cancelled' for t in "
            "drv.ws_checks.get('status', {}).get('turns', {}).values())", timeout=45)
    qa.click(surface='chat_feedback_vote', text='Thumbs up')
    qa.wait(f'any(m.feedback_rating == 5 and m.feedback_status == 2 for m in {SCENE}.mixie_chat_messages)', timeout=45)
    snap(qa, 'feedback')
    return {'backend': endpoint, 'cube': name, 'scene': cube, 'replay_marker_count': 1, 'cancelled': True}


if __name__ == '__main__':
    run_scenario('agent_websocket_e2e', run)
