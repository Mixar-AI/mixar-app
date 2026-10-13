#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Refine / Revert beside Send in the Agent island; no credits, no backend call.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
  QA_SCENARIO_OUT=/tmp/chat-refine python3 tests/qa/chat_prompt_refine_e2e.py
Run in an isolated QA app. Inspect the saved PNGs as well as the state verdict.

Only the refine service is synthetic: it answers from a timer, like the real
async queue, so nothing reaches /prompt-refine and no credit is spent. The
buttons, operators, engine, ChatSlot and island painting are the shipped ones.

Proves:
  1. an empty draft shows Refine disabled and no Revert;
  2. clicking the real island Refine rewrites the draft in place (never
     sends it), stashes the user's words, and Revert joins Refine;
  3. Revert puts the user's own words back and drops Revert;
  4. a refinement still in flight when the composer is cleared (what every
     send does) drops its answer instead of refilling the empty composer;
  5. with a transcript AND a reference attached, Send moves into the
     reference column's region and Refine / Revert ride with it: the click
     still lands and Revert still restores.
"""
import os
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/chat-refine'))
OUT.mkdir(parents=True, exist_ok=True)
REFERENCE = OUT / 'qa-reference.png'
Image.new('RGB', (256, 256), (180, 60, 50)).save(REFERENCE)
REFINE = {'op': 'MIXIE_OT_refine_prompt', 'area_type': 'AGENT_BUBBLE'}
REVERT = {'op': 'MIXIE_OT_revert_prompt', 'area_type': 'AGENT_BUBBLE'}
SEND = {'op': 'MIXIE_CHAT_OT_send_message', 'area_type': 'AGENT_BUBBLE'}
DRAFT = 'make the cube red'
REFINED = 'Make the selected cube a saturated red; keep its other materials.'
SCENE = 'bpy.context.window_manager.windows[0].scene'

SETUP = f"""
import bpy, os
from types import SimpleNamespace
import mixar.modules.common.api.services as S
assert os.environ.get('MIXAR_QA') == '1'
calls = []
class FakeRefine:
    delay = 0.4
    def refine_async(self, prompt, *, service_key='', model_slug='',
                     on_success=None, on_error=None, timeout=None):
        calls.append((prompt, service_key, model_slug))
        def land():
            on_success(SimpleNamespace(data={{'data': {{
                'prompt': {REFINED!r}, 'original_prompt': prompt}}}}))
        bpy.app.timers.register(land, first_interval=self.delay)
        return 'qa'
fake = FakeRefine()
S._qa_chat_refine = (S.get_prompt_refine_service, calls, fake)
S.get_prompt_refine_service = lambda: fake
scene = {SCENE}
scene.mixie_chat_messages.clear()
scene.mixie_chat_input = ''
result = True
"""
CLEANUP = f"""
import mixar.modules.common.api.services as S
scene = {SCENE}
scene.mixie_chat_pending_attachments.clear()
scene.mixie_chat_messages.clear()
scene.mixie_chat_input = ''
saved = getattr(S, '_qa_chat_refine', None)
if saved:
    S.get_prompt_refine_service = saved[0]
    del S._qa_chat_refine
result = True
"""


def state(qa):
    return qa.eval(
        f"s={SCENE}\n"
        "result=dict(input=s.mixie_chat_input, refined=s.mixie_chat_prompt_refined,"
        " refining=s.mixie_chat_prompt_refining, stash=s.mixie_chat_prompt_pre_refine,"
        " messages=len(s.mixie_chat_messages))")


def capture(qa, name):
    qa.eval(f"widget=drv.find_one(**{SEND!r})\nwin=widget['_win']\n"
            "with bpy.context.temp_override(window=win, area=next(iter(win.screen.areas))):\n"
            "    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)\n"
            "result=True")
    time.sleep(.25)
    path = str(OUT / (name + '.png'))
    qa.cmd('snap', path=path, target=SEND, margin=900)
    return path


def run(qa):
    qa.step('wait_login', qa.cmd, 'wait_login', timeout=90)
    qa.step('open_island', qa.eval, 'result=str(bpy.ops.mixar.agent_bubble_show_window())')
    qa.step('install_fixture', qa.eval, SETUP)
    snaps = []
    try:
        # 1. Empty draft: Refine present but disabled, no Revert.
        qa.step('refine_on_island', qa.wait,
                f"len(drv.find(**{REFINE!r})) == 1", timeout=15)
        refine = qa.find(**REFINE)['widgets'][0]
        assert not refine['enabled'], refine
        assert not qa.find(**REVERT)['widgets']
        snaps.append(qa.step('empty_capture', capture, qa, '1_empty_draft'))

        # 2. Type, Refine: rewritten in place, stashed, Revert joins.
        qa.step('type_draft', qa.eval, f"{SCENE}.mixie_chat_input = {DRAFT!r}\nresult=True")
        qa.step('refine_enabled', qa.wait,
                f"drv.find(**{REFINE!r})[0]['enabled']", timeout=5)
        snaps.append(qa.step('typed_capture', capture, qa, '2_typed'))
        qa.step('click_refine', qa.click, **REFINE)
        qa.step('refined', qa.wait,
                f"{SCENE}.mixie_chat_input == {REFINED!r}", timeout=10)
        s = state(qa)
        assert s['refined'] and not s['refining'] and s['stash'] == DRAFT, s
        assert s['messages'] == 0, ('Refine must never send', s)
        calls = qa.eval("import mixar.modules.common.api.services as S\n"
                        "result=[list(c) for c in S._qa_chat_refine[1]]")
        assert calls == [[DRAFT, 'agent_chat', '']], calls
        qa.step('revert_appears', qa.wait,
                f"len(drv.find(**{REVERT!r})) == 1", timeout=5)
        snaps.append(qa.step('refined_capture', capture, qa, '3_refined_with_revert'))

        # 3. Revert: the user's own words, Revert gone.
        qa.step('click_revert', qa.click, **REVERT)
        qa.step('reverted', qa.wait, f"{SCENE}.mixie_chat_input == {DRAFT!r}", timeout=5)
        s = state(qa)
        assert not s['refined'] and s['stash'] == '', s
        qa.step('revert_gone', qa.wait, f"not drv.find(**{REVERT!r})", timeout=5)
        snaps.append(qa.step('reverted_capture', capture, qa, '4_reverted'))

        # 4. In flight when the composer empties (every send does this).
        qa.step('slow_service', qa.eval,
                "import mixar.modules.common.api.services as S\n"
                "S._qa_chat_refine[2].delay = 1.5\nresult=True")
        qa.step('click_refine_again', qa.click, **REFINE)
        qa.step('in_flight', qa.wait, f"{SCENE}.mixie_chat_prompt_refining", timeout=5)
        qa.step('refine_disabled_in_flight', qa.wait,
                f"not drv.find(**{REFINE!r})[0]['enabled']", timeout=5)
        snaps.append(qa.step('in_flight_capture', capture, qa, '5_in_flight'))
        qa.step('clear_composer', qa.eval, f"{SCENE}.mixie_chat_input = ''\nresult=True")
        time.sleep(2.2)
        s = state(qa)
        assert s['input'] == '' and not s['refined'] and not s['refining'], s
        assert s['stash'] == '', s

        # 5. Populated transcript + a reference: Send is hosted by the
        #    reference column (a UI region), and the pair must follow it.
        qa.step('fast_service', qa.eval,
                "import mixar.modules.common.api.services as S\n"
                "S._qa_chat_refine[2].delay = 0.4\nresult=True")
        qa.step('seed_transcript_and_reference', qa.eval,
                f"s={SCENE}\n"
                "m=s.mixie_chat_messages.add()\nm.sender='AGENT'\nm.message_type='AGENT'\n"
                "m.bubble_id='qa-refine'\nm.content='Ready when you are.'\n"
                "a=s.mixie_chat_pending_attachments.add()\n"
                f"a.image_path={str(REFERENCE)!r}\n"
                "a.image_source='FILE'\na.display_name='qa-reference.png'\n"
                f"s.mixie_chat_input={DRAFT!r}\n"
                "from mixar.modules.space_mixie_chat.core.ui_utils import redraw_chat_areas\n"
                "redraw_chat_areas()\nresult=True")
        qa.step('column_up', qa.wait, "bool(drv.find(surface='reference_column'))", timeout=8)
        qa.step('send_in_column', qa.wait,
                f"drv.find(**{SEND!r})[0]['region_type'] == 'UI'", timeout=5)
        qa.step('refine_in_column', qa.wait,
                f"[(w['region_type'], w['enabled']) for w in drv.find(**{REFINE!r})] == [('UI', True)]",
                timeout=5)
        qa.step('click_refine_in_column', qa.click, **REFINE)
        qa.step('refined_in_column', qa.wait,
                f"{SCENE}.mixie_chat_input == {REFINED!r}", timeout=10)
        qa.step('revert_in_column', qa.wait,
                f"[w['region_type'] for w in drv.find(**{REVERT!r})] == ['UI']", timeout=5)
        snaps.append(qa.step('column_capture', capture, qa, '6_reference_column'))
        qa.step('click_revert_in_column', qa.click, **REVERT)
        qa.step('reverted_in_column', qa.wait, f"{SCENE}.mixie_chat_input == {DRAFT!r}", timeout=5)
        return {'snaps': snaps, 'backend_calls': 0}
    finally:
        qa.step('restore_fixture', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('chat_prompt_refine_e2e', run)
