#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Delayed model saves and failed reads through real UI/threads/timers; no credits.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4798 \
  QA_SCENARIO_OUT=/tmp/model-ordering python3 tests/qa/agent_model_ordering_e2e.py
Run in an isolated QA instance. The HTTP boundary is synthetic and restored.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import run_scenario
import model_popup as mp

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/model-ordering'))
OUT.mkdir(parents=True, exist_ok=True)
SETUP = """
import bpy, threading
from types import SimpleNamespace
from mixar.modules.byok.core import preference_client as F, preference_state as P
from mixar.modules.byok.core import model_suggestions as M, credential_state as C
from mixar.modules.space_mixie_chat.core.session import get_session_manager
from mixar.modules.space_mixie_chat.constants import SessionState
saved = (F.get_agent_service, M.get_platform_models, P.snapshot(),
         bpy.context.scene.mixie_chat_input,
         get_session_manager().get_state(bpy.context.scene), C.snapshot())
# Mixie answers here: the account's own key (if any) is set aside in memory.
C.apply_from_payload({'byok_active': False, 'items': []}, bpy.context.window_manager)
get_session_manager().set_state(bpy.context.scene, SessionState.IDLE)
f = SimpleNamespace(release=threading.Event(), read_release=threading.Event(),
                    read_started=False, puts=0, fail_next=False, gets=0, model='original')
def response(data):
    return SimpleNamespace(success=True, status_code=200, data={'data': data})
def view(model):
    return dict(role='default', provider='openai', model=model, label=model)
def get_preference():
    f.gets += 1
    if f.gets == 1:
        old = f.model
        f.read_started = True
        if not f.read_release.wait(45):
            raise RuntimeError('QA delayed GET timed out')
        return response({'items':[view(old)], 'byok_active':False})
    if f.fail_next:
        f.fail_next = False
        return SimpleNamespace(success=False, status_code=503, data={})
    return response({'items':[view(f.model)], 'byok_active':False})
def put_preference(**kwargs):
    f.puts += 1
    if not f.release.wait(45):
        raise RuntimeError('QA delayed PUT timed out')
    f.model = kwargs['model']
    return response(view(f.model))
service = SimpleNamespace(get_model_preference=get_preference, put_model_preference=put_preference)
F.get_agent_service = lambda: service
M.get_platform_models = lambda: [dict(provider_id='openai', provider_label='OpenAI',
    model_id=x, model_label=x, eligible=True, thinking_levels=[]) for x in ('QA A', 'QA B')]
P.clear()
P.apply_from_payload({'items':[view('original')], 'byok_active':False})
P._qa_ordering = (saved, f)
bpy.context.scene.mixie_chat_input = 'QA draft must remain unsent'
P.refresh()
result = True
"""
CLEANUP = """
from mixar.modules.byok.core import preference_client as F, preference_state as P
from mixar.modules.byok.core import model_suggestions as M, credential_state as C
saved, f = P._qa_ordering
cred = saved[5]
# Round-trip the account's real credential mirror back through the parser.
C.apply_from_payload({'byok_active': cred['byok_is_active'], 'items': [dict(
    provider=cred['byok_current_provider'], model=cred['byok_current_model'],
    supports_vision=cred['byok_current_supports_vision'],
    key_preview=cred['byok_key_preview'])]}, bpy.context.window_manager)

f.release.set()
f.read_release.set()
P.clear()
F.get_agent_service, M.get_platform_models = saved[:2]
P.apply_local(saved[2])
bpy.context.scene.mixie_chat_input = saved[3]
from mixar.modules.space_mixie_chat.core.session import get_session_manager
get_session_manager().set_state(bpy.context.scene, saved[4])
del P._qa_ordering
result = True
"""


def run(qa):
    qa.step('open_island', qa.eval, 'result=str(bpy.ops.mixar.agent_bubble_show_window())')
    qa.step('install_fixture', qa.eval, SETUP)
    try:
        qa.step('old_read_started', qa.wait,
                "__import__('mixar.modules.byok.core.preference_state', fromlist=[''])._qa_ordering[1].read_started",
                timeout=10)
        qa.step('open_popup', mp.open_popup, qa)
        qa.step('choose_A', mp.pick, qa, 'QA A')
        qa.step('assert_send_and_second_write_blocked', qa.eval, """
from mixar.modules.byok.core import preference_state as P
assert P.mutation_pending()
assert not bpy.ops.mixie_chat.send_message.poll()
assert not bpy.ops.mixar.agent_pick.poll()
assert bpy.context.scene.mixie_chat_input == 'QA draft must remain unsent'
assert P._qa_ordering[1].model == 'original'
result = True
""")
        qa.step('pending_popup', mp.open_popup, qa)
        if any(enabled for _, enabled in mp.rows(qa)):
            raise RuntimeError(f'A pick row is live while a save is pending: {mp.rows(qa)}')
        pending = str(OUT / 'pending.png')
        qa.step('snap_pending', qa.cmd, 'snap', path=pending, target=mp.CARD, margin=80)
        mp.close_popup(qa)
        qa.step('acknowledge_save', qa.eval,
                "from mixar.modules.byok.core import preference_state as P\n"
                "P._qa_ordering[1].release.set()\nresult = True")
        qa.step('wait_confirmed', qa.wait,
                "bpy.context.window_manager.mixar_agent_model_label == 'QA A' and "
                "bpy.ops.mixie_chat.send_message.poll()", timeout=10)
        qa.step('release_stale_read', qa.eval,
                "from mixar.modules.byok.core import preference_state as P\n"
                "P._qa_ordering[1].read_release.set()\nresult = True")
        # Wait for the old worker's callback to pass through the main loop.
        time.sleep(1)
        qa.step('assert_confirmed_pick_and_draft', qa.eval, """
from mixar.modules.byok.core import preference_state as P
assert P.snapshot()['mixar_agent_model_id'] == 'QA A'
assert bpy.context.scene.mixie_chat_input == 'QA draft must remain unsent'
assert P._qa_ordering[1].puts == 1
P.apply_local({'mixar_agent_model_byok_active': True})
P._qa_ordering[1].fail_next = True
P.refresh()
result = True
""")
        qa.step('wait_independent_retry', qa.wait,
                "not bpy.context.window_manager.mixar_agent_model_byok_active", timeout=25)
        recovered = str(OUT / 'recovered.png')
        qa.step('open_recovered_popup', mp.open_popup, qa)
        qa.step('snap_recovered', qa.cmd, 'snap', path=recovered, target=mp.CARD, margin=80)
        mp.close_popup(qa)
        return {'snaps': [pending, recovered], 'real_backend_mutations': 0}
    finally:
        qa.step('restore_fixture', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('agent_model_ordering_e2e', run)
