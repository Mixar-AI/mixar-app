#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""BYOK per-turn passthrough, end to end in the real app (spends NO Mixar credits).

The backend keeps BYOK metadata only; the key lives in this device's credential
store and rides every `chat` / `input` command. Driven against a backend on the
PR's branch, with the QA account's legacy rows or none. Steps:

1. Boot: the mirror agrees with the server; if BYOK is active but this device
   holds no record, `byok_device_key_missing` is True.
2. Keyless chat under active BYOK → the 409 bubble (server message + the
   settings hint), no turn runs, the pill says "key needed".
3. Save an OpenAI key through the dialog operator (`QA_BYOK_OPENAI_KEY`):
   SAVED, record in the store, masked preview on the server, pill clear.
4. Chat → the agent answers; the turn ran on the user's key.
5. Second device: drop the record → chat → 409 bubble, pill "key needed";
   an `input` abort is still sent (server-exempt, never refused client-side).
6. Foreign-provider record (the account was switched elsewhere) → not sent,
   409, pill "key needed"; restoring it clears the pill.
7. Cold-start window (mirror not loaded): the send goes out keyless and the
   409 refreshes the mirror instead of flipping the pill blindly.
8. A device-store write that fails after the 200 is an ERROR carrying the
   server state, not a SAVED recap.
9. Remove through the dialog: rows gone, record gone, mirror inactive.

Skipped (reported, not failed) without `QA_BYOK_OPENAI_KEY`. The Codex path
(the CLI's auth.json read in place → access token + account id only) is the
same operator with `byok_form_codex_path`; it is exercised manually, never
from a scenario, because it uses a real ChatGPT sign-in.

QA_HARNESS=/path/to/mixar-qa-harness QA_BYOK_OPENAI_KEY=sk-... \
    QA_SCENARIO_OUT=/tmp/byok-passthrough python3 tests/qa/byok_passthrough_e2e.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA, ScenarioFail, run_scenario  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/byok-passthrough'))
KEY = os.environ.get('QA_BYOK_OPENAI_KEY', '')
MODEL = os.environ.get('QA_BYOK_OPENAI_MODEL', 'gpt-5-mini')
SETTINGS_HINT = 'AI Provider Settings'

STATE = """
from mixar.modules.byok.core import credential_state, key_store
wm = bpy.data.window_managers[0]
scene = drv.main_window().scene
r = key_store.load()
result = {
  'mirror': credential_state.snapshot(),
  'dialog': wm.byok_dialog_state, 'last_error': wm.byok_last_error,
  'record': None if r is None else {'provider': r.get('provider'), 'has_key': bool(r.get('key'))},
  'chat_state': scene.mixie_chat_state, 'busy': bool(scene.mixie_chat_is_busy),
  'messages': [(m.sender, (m.text or '')[:300]) for m in scene.mixie_chat_messages][-3:],
}
"""
IDLE = ("(not drv.main_window().scene.mixie_chat_is_busy) and "
        "drv.main_window().scene.mixie_chat_state == 'IDLE'")
LOADED = "__import__('mixar.modules.byok.core.credential_state', fromlist=['x']).snapshot()['byok_state_loaded']"
MISSING = "__import__('mixar.modules.byok.core.credential_state', fromlist=['x']).snapshot()['byok_device_key_missing']"
DIALOG_DONE = "bpy.data.window_managers[0].byok_dialog_state in ('SAVED','ERROR','REMOVED')"


def state(qa):
    return qa.eval(STATE)


def last_agent(s):
    agents = [t for who, t in s['messages'] if who == 'AGENT']
    return agents[-1] if agents else ''


def chat(qa, text, timeout=240):
    qa.chat_send(text)
    qa.wait(IDLE, timeout=timeout)
    return state(qa)


def expect_409(qa, text, why):
    s = chat(qa, text)
    msg = last_agent(s)
    if 'did not send' not in msg or SETTINGS_HINT not in msg:
        raise ScenarioFail(f'{why}: expected the byok_key_required bubble, got {msg[:120]!r}')
    if not s['mirror']['byok_device_key_missing']:
        raise ScenarioFail(f'{why}: pill did not flip to "key needed"')
    return s


def save_openai(qa):
    qa.eval(f"""
wm = bpy.data.window_managers[0]
wm.byok_form_provider = 'openai'
wm.byok_form_model = {MODEL!r}
wm.byok_form_api_key = {KEY!r}
wm.byok_dialog_state = 'IDLE'
result = list(bpy.ops.mixar_byok.save())
""")
    qa.wait(DIALOG_DONE, timeout=60)
    return state(qa)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.wait(LOADED, timeout=60)
    boot = state(qa)
    notes = {'boot_active': boot['mirror']['byok_is_active'], 'boot_record': boot['record']}
    if not KEY:
        return {**notes, 'skipped': 'QA_BYOK_OPENAI_KEY not set'}

    # Start from a clean account so every step has one precondition.
    if boot['mirror']['byok_is_active']:
        qa.eval("wm = bpy.data.window_managers[0]; wm.byok_dialog_state = 'CONFIRM_REMOVE'; "
                "result = list(bpy.ops.mixar_byok.confirm_remove())")
        qa.wait(DIALOG_DONE, timeout=60)
    qa.eval("from mixar.modules.byok.core import key_store; result = key_store.delete()")

    s = qa.step('save openai key', save_openai, qa)
    if s['dialog'] != 'SAVED' or not s['mirror']['byok_is_active'] or s['record'] != {'provider': 'openai', 'has_key': True}:
        raise ScenarioFail(f'save: {s["dialog"]} {s["last_error"]!r} record={s["record"]}')
    if not s['mirror']['byok_key_preview'].startswith('sk-') or s['mirror']['byok_device_key_missing']:
        raise ScenarioFail('save: preview or pill wrong')

    s = qa.step('chat on the key', chat, qa, 'Reply with the single word pong.')
    if 'pong' not in last_agent(s).lower():
        raise ScenarioFail(f'chat on key: {last_agent(s)[:120]!r}')
    qa.snap(str(OUT / 'byok-turn-on-key.png'))

    qa.step('second device: drop the record', qa.eval,
            "from mixar.modules.byok.core import key_store, credential_state; key_store.delete(); credential_state.refresh(); result = True")
    qa.wait(MISSING, timeout=20)
    qa.step('keyless chat is refused with the 409 bubble', expect_409, qa, 'Say pong again.', 'second device')
    sent = qa.eval("""
from mixar.modules.space_mixie_chat.core.turn_transport import create_turn_handler
from mixar.modules.space_mixie_chat.core.session import get_session_manager
scene = drv.main_window().scene
h = create_turn_handler(scene_name=scene.name)
result = h.start_input_stream(session_id=get_session_manager().get_session_id(scene), action='abort')
""")
    if sent is not True:
        raise ScenarioFail('abort without a device key was refused client-side')
    time.sleep(2)
    if state(qa)['busy']:
        raise ScenarioFail('abort left the session busy')

    qa.step('re-save (key-only re-entry on this device)', save_openai, qa)
    qa.step('foreign-provider record is not sent', qa.eval,
            "from mixar.modules.byok.core import key_store; result = key_store.update({'provider': 'anthropic'})")
    qa.step('…so the server 409s and the pill flips', expect_409, qa, 'Say pong once more.', 'foreign provider')
    qa.eval("from mixar.modules.byok.core import key_store, credential_state; key_store.update({'provider': 'openai'}); credential_state.refresh(); result = True")
    qa.wait('not ' + MISSING, timeout=20)

    qa.step('cold-start window: mirror unloaded', qa.eval,
            "from mixar.modules.byok.core import credential_state; "
            "credential_state._state = dict(credential_state._state, byok_state_loaded=False, byok_is_active=False); result = True")
    s = chat(qa, 'Say pong (cold).')
    if 'did not send' not in last_agent(s) or not s['mirror']['byok_state_loaded'] or s['mirror']['byok_device_key_missing']:
        raise ScenarioFail('cold start: the 409 must refresh the mirror, not flip the pill')

    qa.step('device-store write failure is an ERROR with the server state', qa.eval,
            "from mixar.modules.byok.core import key_store; key_store._qa_save = key_store.save; "
            "key_store.save = lambda record, user_id=None: False; result = True")
    s = save_openai(qa)
    qa.eval("from mixar.modules.byok.core import key_store; key_store.save = key_store._qa_save; result = True")
    if s['dialog'] != 'ERROR' or 'could not be stored on this device' not in s['last_error'] or not s['mirror']['byok_is_active']:
        raise ScenarioFail(f'store failure: {s["dialog"]} {s["last_error"]!r}')
    save_openai(qa)

    qa.eval("""
import bpy
win = drv.main_window()
with bpy.context.temp_override(window=win, area=win.screen.areas[0]):
    result = list(bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT'))
""")
    time.sleep(1.5)
    qa.snap(str(OUT / 'byok-dialog-active.png'))
    qa.press('ESC')

    s = qa.step('remove through the dialog', lambda: (qa.eval(
        "wm = bpy.data.window_managers[0]; wm.byok_dialog_state = 'CONFIRM_REMOVE'; "
        "result = list(bpy.ops.mixar_byok.confirm_remove())"), qa.wait(DIALOG_DONE, timeout=60), state(qa))[-1])
    if s['mirror']['byok_is_active'] or s['record'] is not None:
        raise ScenarioFail(f'remove: active={s["mirror"]["byok_is_active"]} record={s["record"]}')
    return notes


if __name__ == '__main__':
    run_scenario('byok_passthrough_e2e', run)
