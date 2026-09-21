#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Remove a synthetic BYOK credential through the real dialog, then pick a model.

No credentials or preferences are written to the backend. Only the HTTP service
boundary is replaced; actual worker threads, timers, operators and UI run.
Use an isolated QA instance. All replaced functions/state are restored finally.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4796 \
    QA_SCENARIO_OUT=/tmp/byok-remove-qa python3 tests/qa/agent_model_byok_remove_e2e.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/byok-remove-qa'))
OUT.mkdir(parents=True, exist_ok=True)

SETUP = """
import bpy
from types import SimpleNamespace
from mixar.modules.byok.core import byok_client as B, preference_client as F
from mixar.modules.byok.core import credential_state as C, preference_state as P
from mixar.modules.byok.core import model_suggestions as M
from mixar.modules.byok.ui.operators import byok_ops as O
saved = (B.get_agent_service, F.get_agent_service, M.get_platform_models,
         O._deregister_local_if_switched_away, C.snapshot(), P.snapshot())
fixture = SimpleNamespace(active=True, fetches=0, deletes=0, puts=0)
payload = {'byok_active': True, 'items': [{'provider': 'openai',
           'model': 'qa-model', 'key_preview': 'QA fixture (no real key)'}]}
def response(data):
    return SimpleNamespace(success=True, status_code=200, data={'data': data})
def get_preference():
    fixture.fetches += 1
    return response({'byok_active': fixture.active, 'items': []})
def delete_credentials():
    fixture.deletes += 1
    fixture.active = False
    return response({'removed': 1})
def put_preference(**kwargs):
    fixture.puts += 1
    return response({'byok_active': False, 'items': [dict(kwargs, label='QA Hosted')]})
service = SimpleNamespace(get_model_preference=get_preference,
    get_credentials=lambda: response(dict(payload, byok_active=fixture.active)),
    delete_credentials_all=delete_credentials, put_model_preference=put_preference)
B.get_agent_service = F.get_agent_service = lambda: service
O._deregister_local_if_switched_away = lambda provider: None
M.get_platform_models = lambda: [dict(provider_id='openai', provider_label='OpenAI',
    model_id='qa-model', model_label='QA Hosted', eligible=True, thinking_levels=[])]
C.clear()
P.clear()
C.apply_from_payload(payload)
P.apply_from_payload({'byok_active': True, 'items': []})
P._redraw()
O._qa_remove_fixture = (saved, fixture)
result = True
"""

CLEANUP = """
from mixar.modules.byok.core import byok_client as B, preference_client as F
from mixar.modules.byok.core import credential_state as C, preference_state as P
from mixar.modules.byok.core import model_suggestions as M
from mixar.modules.byok.ui.operators import byok_ops as O
saved, fixture = O._qa_remove_fixture
B.get_agent_service, F.get_agent_service, M.get_platform_models = saved[:3]
O._deregister_local_if_switched_away = saved[3]
C.clear()
with C._lock:
    C._state = saved[4]
C.apply_to_wm()
P.clear()
P.apply_local(saved[5])
del O._qa_remove_fixture
result = True
"""

DUMP = """
import bpy, json
result = json.loads(bpy.data.window_managers[0].mixar_qa_ui_dump)['widgets']
"""
PICKER = {'op': 'WM_OT_call_menu', 'area_type': 'MIXIE_CHAT'}
ISLAND_PICKER = {'op': 'WM_OT_call_menu', 'area_type': 'AGENT_BUBBLE'}


def menu_snapshot(qa, enabled, name, picker=PICKER):
    if picker == ISLAND_PICKER:
        qa.step(name + '_expand', qa.open_chat)
    qa.step(name + '_open', qa.click, **picker)
    qa.wait("any(w.get('popup') and w.get('op') == 'MIXAR_OT_agent_model_set' "
            "for w in __import__('json').loads(bpy.data.window_managers[0].mixar_qa_ui_dump)['widgets'])",
            timeout=10)
    rows = qa.eval(DUMP)
    models = [w for w in rows if w.get('popup')
              and w.get('op') == 'MIXAR_OT_agent_model_set']
    if len(models) != 1 or models[0]['enabled'] is not enabled:
        raise ScenarioFail(f'Expected one model row enabled={enabled}: {models}')
    areas = qa.eval(
        f"result = [a.type for w in bpy.context.window_manager.windows "
        f"if w.as_pointer() == {models[0]['w']} for a in w.screen.areas]")
    if picker['area_type'] not in areas:
        raise ScenarioFail(f"Menu opened in {areas}, expected {picker['area_type']}")
    time.sleep(1)
    path = str(OUT / (name + '.png'))
    qa.step(name + '_snap', qa.cmd, 'snap', path=path,
            target={'op': 'MIXAR_OT_agent_model_set', 'popup': True,
                    'window': models[0]['w']}, margin=500)
    qa.cmd('press', key='ESC', window=models[0]['w'])
    return path


def run(qa):
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('open_island', qa.open_chat)
    qa.step('open_footer_editor', qa.eval,
            "area = next(a for w in bpy.context.window_manager.windows "
            "for a in w.screen.areas if a.type in {'VIEW_3D', 'MIXIE_CHAT'})\n"
            "area.type = 'MIXIE_CHAT'\nresult = True")
    qa.step('install_service_fixture', qa.eval, SETUP)
    try:
        before = menu_snapshot(qa, False, 'before_removal')
        island_before = menu_snapshot(qa, False, 'island_before_removal', ISLAND_PICKER)
        qa.step('expand_for_settings', qa.open_chat)
        qa.step('open_settings_from_island', qa.cmd, 'choose',
                widget={'op': 'WM_OT_call_menu', 'area_type': 'AGENT_BUBBLE'},
                item='API key', contains=True)
        qa.step('wait_settings', qa.wait,
                "bpy.context.window_manager.byok_dialog_state == 'IDLE'", timeout=10)
        qa.step('request_remove', qa.click,
                op='MIXAR_BYOK_OT_request_remove', popup=True)
        qa.step('confirm_remove', qa.click,
                op='MIXAR_BYOK_OT_confirm_remove', popup=True)
        qa.step('wait_removed_and_picker_refreshed', qa.wait,
                "bpy.context.window_manager.byok_dialog_state == 'REMOVED' and "
                "not bpy.context.window_manager.mixar_agent_model_byok_active", timeout=10)
        rows = qa.eval(DUMP)
        window = next(w['w'] for w in rows if w.get('popup'))
        qa.cmd('press', key='ESC', window=window)
        after = menu_snapshot(qa, True, 'after_removal')
        island_after = menu_snapshot(qa, True, 'island_after_removal', ISLAND_PICKER)
        qa.step('expand_for_model_selection', qa.open_chat)
        qa.step('choose_hosted_model_in_island', qa.cmd, 'choose', widget=ISLAND_PICKER,
                item='QA Hosted', contains=True)
        qa.step('wait_pick', qa.wait,
                "bpy.context.window_manager.mixar_agent_model_label == 'QA Hosted'", timeout=10)
        qa.step('expand_to_verify_label', qa.open_chat)
        time.sleep(1)
        selected = str(OUT / 'island_selected.png')
        qa.step('snap_selected_island', qa.cmd, 'snap', path=selected,
                target=ISLAND_PICKER, margin=1500)
        footer_selected = str(OUT / 'footer_selected.png')
        qa.step('snap_selected_footer', qa.cmd, 'snap', path=footer_selected,
                target=PICKER, margin=250)
        counts = qa.eval(
            "from mixar.modules.byok.ui.operators import byok_ops as O\n"
            "f = O._qa_remove_fixture[1]\n"
            "result = {'deletes': f.deletes, 'fetches': f.fetches, 'puts': f.puts}")
        if counts != {'deletes': 1, 'fetches': 1, 'puts': 1}:
            raise ScenarioFail(f'Unexpected service calls: {counts}')
        return {'service_calls': counts,
                'snaps': [before, after, island_before, island_after,
                          selected, footer_selected],
                'transport': 'synthetic service; real UI, worker threads and timers'}
    finally:
        rows = qa.eval(DUMP)
        for window in {w['w'] for w in rows if w.get('popup')}:
            qa.cmd('press', key='ESC', window=window)
        qa.step('restore_service_and_state', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('agent_model_byok_remove_e2e', run)
