#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Cinema-styled island model picker; no credits or real preference mutations.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4836 \
  QA_SCENARIO_OUT=/tmp/model-picker python3 tests/qa/agent_model_cinema_picker_e2e.py
Run in an isolated QA app. Inspect the saved PNGs as well as the state verdict.
Only catalog/service responses are fixtures; native menus, clicks, operators,
worker threads and preference mirrors are real. No credentials are accessed.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/model-picker'))
OUT.mkdir(parents=True, exist_ok=True)
PICKER = {'but_type': 'Pulldown', 'area_type': 'AGENT_BUBBLE'}
MODEL = {'op': 'MIXAR_OT_agent_model_set', 'popup': True}
RESET = {'op': 'MIXAR_OT_agent_model_reset', 'popup': True}
SETUP = """
import bpy, os
from types import SimpleNamespace
from mixar.modules.byok.core import preference_client as F, preference_state as P
from mixar.modules.byok.core import model_suggestions as M
assert os.environ.get('MIXAR_QA') == '1'
assert not P.mutation_pending()
saved = (F.get_agent_service, M.get_platform_models, P.snapshot(),
         bpy.context.preferences.view.show_tooltips)
f = SimpleNamespace(items=[], puts=0, deletes=0)
records = [dict(provider_id='qa-provider', provider_label='Hidden Provider',
    model_id='qa-model', model_label='QA Model', eligible=True,
    thinking_levels=['low', 'high']),
    dict(provider_id='qa-provider', provider_label='Hidden Provider',
    model_id='qa-locked', model_label='QA Locked', eligible=False, thinking_levels=[])]
f.records = records
M.get_platform_models = lambda: f.records
response = lambda data: SimpleNamespace(success=True, status_code=200, data={'data': data})
def put(**kwargs):
    f.puts += 1
    f.items = [dict(role='default', provider=kwargs['provider'], model=kwargs['model'],
                   label='Hidden Provider · QA Model',
                   thinking_level=kwargs.get('thinking_level') or '')]
    return response(f.items[0])
def delete(role):
    f.deletes += 1
    f.items = []
    return response({'removed': 1})
service = SimpleNamespace(get_model_preference=lambda: response({'items': f.items}),
                          put_model_preference=put, delete_model_preference=delete)
F.get_agent_service = lambda: service
P.clear()
P.apply_from_payload({'items': [], 'byok_active': False})
P._qa_cinema_picker = (saved, f)
bpy.context.preferences.view.show_tooltips = False
P._redraw()
result = True
"""
CLEANUP = """
from mixar.modules.byok.core import preference_client as F, preference_state as P
from mixar.modules.byok.core import model_suggestions as M
saved, f = P._qa_cinema_picker
P.clear()
F.get_agent_service, M.get_platform_models = saved[:2]
P.apply_local(saved[2])
bpy.context.preferences.view.show_tooltips = saved[3]
del P._qa_cinema_picker
result = True
"""


def close_menus(qa):
    for _ in range(2):
        widgets = qa.find(popup=True)['widgets']
        if not widgets:
            return
        for window in {widget['window'] for widget in widgets}:
            qa.press('ESC', window=window)
        time.sleep(.2)
    qa.wait('not bool(drv.find(popup=True))', timeout=5)


def open_picker(qa):
    qa.click(**PICKER)
    # The first native click after opening a fresh island can commit its
    # composer focus. Retry once only when the popup demonstrably stayed shut.
    if not qa.find(op='MIXAR_BYOK_OT_open_dialog', popup=True)['widgets']:
        qa.click(**PICKER)
    qa.wait("bool(drv.find(op='MIXAR_BYOK_OT_open_dialog', popup=True))", timeout=5)


def capture(qa, name, target):
    qa.eval(f"widget=drv.find_one(**{target!r})\n"
            "win=widget['_win']\n"
            "with bpy.context.temp_override(window=win, area=next(iter(win.screen.areas))):\n"
            "    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)\n"
            "result=True")
    time.sleep(.25)
    path = str(OUT / (name + '.png'))
    qa.cmd('snap', path=path, target=target, margin=1500)
    return path


def run(qa):
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('open_island', qa.eval, 'result=str(bpy.ops.mixar.agent_bubble_show_window())')
    qa.step('install_fixture', qa.eval, SETUP)
    snaps = []
    try:
        qa.step('open_default', open_picker, qa)
        rows = qa.find(**MODEL)['widgets']
        assert [r['text'] for r in rows] == ['QA Model', 'QA Locked'], rows
        assert [r['enabled'] for r in rows] == [True, False], rows
        assert all(r.get('mixar_component') == 'legacy_card' for r in rows), rows
        assert qa.find(**RESET)['widgets'][0]['text'] == 'Mixie'
        snaps.append(qa.step('default_capture', capture, qa, 'default', RESET))
        qa.step('choose_model', qa.click, **MODEL, text='QA Model')
        qa.step('saved_model', qa.wait,
                "bpy.context.window_manager.mixar_agent_model_id == 'qa-model' and "
                "not __import__('mixar.modules.byok.core.preference_state', fromlist=['']).mutation_pending()",
                timeout=10)
        qa.step('model_only_chip', qa.eval,
                "assert bpy.context.window_manager.mixar_agent_model_label == 'QA Model'\nresult=True")
        qa.step('open_selected', open_picker, qa)
        snaps.append(qa.step('selected_capture', capture, qa, 'selected', RESET))
        qa.step('open_thinking', qa.click, text='Thinking', popup=True)
        qa.wait("bool(drv.find(text='Thinking: High', popup=True))", timeout=5)
        snaps.append(qa.step('thinking_capture', capture, qa, 'thinking',
                             dict(text='Thinking: High', popup=True)))
        qa.step('choose_thinking', qa.click, text='Thinking: High', popup=True)
        qa.step('saved_thinking', qa.wait,
                "bpy.context.window_manager.mixar_agent_model_thinking == 'high' and "
                "not __import__('mixar.modules.byok.core.preference_state', fromlist=['']).mutation_pending()",
                timeout=10)
        close_menus(qa)
        qa.step('open_for_default', open_picker, qa)
        qa.step('choose_mixie', qa.click, **RESET)
        qa.step('default_clears_preference', qa.wait,
                "not bpy.context.window_manager.mixar_agent_model_id and "
                "not __import__('mixar.modules.byok.core.preference_state', fromlist=['']).mutation_pending()",
                timeout=10)
        qa.step('verify_default_and_byok', qa.eval, """
from mixar.modules.byok.core import preference_state as P
assert P._qa_cinema_picker[1].puts == 2
assert P._qa_cinema_picker[1].deletes == 1
assert not P.snapshot()['mixar_agent_model_label']
P.apply_local({'mixar_agent_model_byok_active': True})
result=True
""")
        qa.step('open_byok', open_picker, qa)
        assert all(not r['enabled'] for r in qa.find(**MODEL)['widgets'])
        assert qa.find(op='MIXAR_BYOK_OT_open_dialog', popup=True)['widgets'][0]['enabled']
        snaps.append(qa.step('byok_capture', capture, qa, 'byok', RESET))
        close_menus(qa)
        qa.step('empty_catalog', qa.eval, """
from mixar.modules.byok.core import preference_state as P
P._qa_cinema_picker[1].records = []
P._redraw()
result=True
""")
        qa.step('open_empty', open_picker, qa)
        assert not qa.find(**MODEL)['widgets'] and not qa.find(**RESET)['widgets']
        empty = qa.find(text='No models available — contact support', popup=True)['widgets']
        assert len(empty) == 1 and not empty[0]['enabled']
        snaps.append(qa.step('empty_capture', capture, qa, 'empty',
                             dict(op='MIXAR_BYOK_OT_open_dialog', popup=True)))
        return {'snaps': snaps, 'real_backend_mutations': 0}
    finally:
        close_menus(qa)
        qa.step('restore_fixture', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('agent_model_cinema_picker_e2e', run)
