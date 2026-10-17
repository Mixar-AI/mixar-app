#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The island model popup's Mixie tab (Cinema rows); no credits or real preference mutations.

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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import run_scenario
import model_popup as mp

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/model-picker'))
OUT.mkdir(parents=True, exist_ok=True)
PENDING = "__import__('mixar.modules.byok.core.preference_state', fromlist=['']).mutation_pending()"
SETUP = """
import bpy, os
from types import SimpleNamespace
from mixar.modules.byok.core import preference_client as F, preference_state as P
from mixar.modules.byok.core import model_suggestions as M, credential_state as C
assert os.environ.get('MIXAR_QA') == '1'
assert not P.mutation_pending()
saved = (F.get_agent_service, M.get_platform_models, P.snapshot(),
         bpy.context.preferences.view.show_tooltips, C.snapshot())
# Mixie answers here: the account's own key (if any) is set aside in memory.
C.apply_from_payload({'byok_active': False, 'items': []}, bpy.context.window_manager)
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
from mixar.modules.byok.core import model_suggestions as M, picker_mirror, credential_state as C
saved, f = P._qa_cinema_picker
cred = saved[4]
# Round-trip the account's real credential mirror back through the parser.
C.apply_from_payload({'byok_active': cred['byok_is_active'], 'items': [dict(
    provider=cred['byok_current_provider'], model=cred['byok_current_model'],
    supports_vision=cred['byok_current_supports_vision'],
    key_preview=cred['byok_key_preview'])]}, bpy.context.window_manager)

P.clear()
F.get_agent_service, M.get_platform_models = saved[:2]
P.apply_local(saved[2])
picker_mirror.apply_to_wm()
bpy.context.preferences.view.show_tooltips = saved[3]
del P._qa_cinema_picker
result = True
"""


def close_menus(qa):
    mp.close_popup(qa)


def open_picker(qa):
    mp.open_popup(qa)
    if mp.open_tab(qa) != 'MIXIE':
        raise AssertionError(f'The popup opened on {mp.open_tab(qa)}, not Mixie')


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
        # Ineligible rows are greyed, not hidden, and say why.
        assert mp.rows(qa) == [('Mixar default', True), ('QA Model', True),
                               ('QA Locked', False)], mp.rows(qa)
        snaps.append(qa.step('default_capture', capture, qa, 'default', mp.PICK))
        qa.step('choose_model', mp.pick, qa, 'QA Model')
        qa.step('saved_model', qa.wait,
                f"bpy.context.window_manager.mixar_agent_model_id == 'qa-model' and not {PENDING}",
                timeout=10)
        qa.step('model_only_chip', qa.eval,
                "assert bpy.context.window_manager.mixar_agent_chip_name == 'QA Model'\nresult=True")
        qa.step('open_selected', open_picker, qa)
        snaps.append(qa.step('selected_capture', capture, qa, 'selected', mp.PICK))
        # The disclosure re-lays the popup with the model's levels in place.
        qa.step('open_thinking', qa.click, **mp.THINKING)
        qa.wait(f"bool(drv.find(**{mp.PICK!r}, text='High'))", timeout=5)
        snaps.append(qa.step('thinking_capture', capture, qa, 'thinking',
                             dict(mp.PICK, text='High')))
        qa.step('choose_thinking', mp.pick, qa, 'High')
        qa.step('saved_thinking', qa.wait,
                f"bpy.context.window_manager.mixar_agent_model_thinking == 'high' and not {PENDING}",
                timeout=10)
        qa.wait("bpy.context.window_manager.mixar_agent_chip_name == 'QA Model · High'", timeout=5)
        close_menus(qa)
        qa.step('open_for_default', open_picker, qa)
        qa.step('choose_default', mp.pick, qa, 'Mixar default')
        qa.step('default_clears_preference', qa.wait,
                f"not bpy.context.window_manager.mixar_agent_model_id and not {PENDING}",
                timeout=10)
        qa.step('verify_default', qa.eval, """
from mixar.modules.byok.core import preference_state as P
assert P._qa_cinema_picker[1].puts == 2
assert P._qa_cinema_picker[1].deletes == 1
assert not P.snapshot()['mixar_agent_model_label']
result=True
""")
        qa.step('empty_catalog', qa.eval, """
from mixar.modules.byok.core import preference_state as P, picker_mirror
P._qa_cinema_picker[1].records = []
picker_mirror.apply_to_wm()
result=True
""")
        qa.step('open_empty', open_picker, qa)
        assert not mp.rows(qa), mp.rows(qa)
        empty = qa.find(surface='model_card_note', text='No models available — contact support')['widgets']
        assert len(empty) == 1, empty
        snaps.append(qa.step('empty_capture', capture, qa, 'empty', mp.TAB))
        return {'snaps': snaps, 'real_backend_mutations': 0}
    finally:
        close_menus(qa)
        qa.step('restore_fixture', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('agent_model_cinema_picker_e2e', run)
