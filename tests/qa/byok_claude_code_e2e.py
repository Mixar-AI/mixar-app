#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay the real Claude form, sign-out failure, save, switch and resume.

Use an isolated MIXAR_QA=1 app with an in-memory credential store. Only CLI
status and HTTP mutations are synthetic; native clicks, workers, callbacks,
record storage and state mirrors are real. No real subscription/account changes.
QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4796 python3 <this-file>
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/private/tmp/claude-provider-evidence'))
OUT.mkdir(parents=True, exist_ok=True)

SETUP = '''
import bpy, os
from types import SimpleNamespace
from mixar.modules.byok.core import byok_client as B, claude_code as C, credential_state as S, key_store as K, preference_state as P
assert os.environ.get('MIXAR_QA') == '1'
f = SimpleNamespace(saved=(B._put_sealed, C.check_ready, P.refresh, S.snapshot(), K.load()), puts=[], replies=[])
C._qa_fixture = f
P.refresh = lambda *a, **kw: None
def put(provider, model, api_key, *args, **kw):
    assert provider == 'claude_code' and api_key is None
    f.puts.append({'provider': provider, 'model': model, 'api_key': api_key})
    return True, {'byok_active': True, 'items': [{'provider': provider, 'model': model, 'key_preview': 'Claude Code on this computer', 'supports_vision': True}]}, None
B._put_sealed = put
def signed_out():
    raise C.ClaudeCodeError('claude_login_required', 'Run claude auth login in your terminal, then Save & Activate.')
C.check_ready = signed_out
S.apply_from_payload({'byok_active': False, 'items': []})
wm = bpy.context.window_manager
wm.byok_dialog_state = 'IDLE'
wm.byok_form_provider = 'claude_code'
result = True
'''


def close(qa):
    widgets = qa.find(popup=True)['widgets']
    for window in {w['window'] for w in widgets}:
        qa.press('ESC', window=window)


def run(qa):
    close(qa)
    qa.eval(SETUP)
    try:
        qa.eval("win=drv.main_window()\narea=max(win.screen.areas,key=lambda a:a.width*a.height)\nwith bpy.context.temp_override(window=win,area=area):\n bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT')\nresult=True")
        qa.wait("bool(drv.find(op='MIXAR_BYOK_OT_save', popup=True))", timeout=10)
        qa.eval("bpy.context.window_manager.byok_form_provider='claude_code'\nresult=True")
        qa.step('form_has_models_and_no_secret_field', qa.wait,
                "bpy.context.window_manager.byok_form_provider=='claude_code' and "
                "not any(w.get('prop')=='byok_form_api_key' for w in drv.find(popup=True))", timeout=10)
        qa.snap(str(OUT / 'setup.png'))
        qa.step('save_signed_out', qa.click, op='MIXAR_BYOK_OT_save', popup=True)
        qa.wait("bpy.context.window_manager.byok_dialog_state=='ERROR'", timeout=10)
        qa.eval("assert 'claude auth login' in bpy.context.window_manager.byok_last_error\nassert not __import__('mixar.modules.byok.core.claude_code',fromlist=['x'])._qa_fixture.puts\nresult=True")
        qa.snap(str(OUT / 'login-required.png'))
        qa.eval("from mixar.modules.byok.core import claude_code as C\nC.check_ready=lambda: None\nresult=True")
        qa.step('save_signed_in', qa.click, op='MIXAR_BYOK_OT_save', popup=True)
        qa.wait("bpy.context.window_manager.byok_dialog_state=='SAVED'", timeout=10)
        record = qa.eval("from mixar.modules.byok.core import key_store as K\nr=K.load()\nassert r['provider']=='claude_code' and r['key'] is None\nresult=r")
        qa.snap(str(OUT / 'saved.png'))
        close(qa)
        qa.eval("from mixar.modules.byok.core import byok_client as B, claude_code as C, credential_state as S\nS.apply_from_payload({'byok_active':False,'items':[]})\nB.resave_stored_key(None, lambda ok,data,error: (C._qa_fixture.replies.append(ok),S.apply_from_payload(data) if ok else None))\nresult=True")
        qa.step('resume_keyless_provider', qa.wait,
                "bpy.context.window_manager.byok_is_active and "
                "__import__('mixar.modules.byok.core.claude_code',fromlist=['x'])._qa_fixture.replies==[True]", timeout=10)
        puts = qa.eval("from mixar.modules.byok.core import claude_code as C\nresult=C._qa_fixture.puts")
        assert len(puts) == 2 and all(p['api_key'] is None for p in puts)
        return {'record': record, 'puts': puts, 'snaps': [str(OUT / n) for n in ('setup.png','login-required.png','saved.png')]}
    finally:
        close(qa)
        qa.eval("from mixar.modules.byok.core import byok_client as B, claude_code as C, credential_state as S, key_store as K, preference_state as P\nf=C._qa_fixture\nB._put_sealed,C.check_ready,P.refresh=f.saved[:3]\nS._state = dict(f.saved[3])\nS.apply_to_wm()\nK.save(f.saved[4]) if f.saved[4] else K.delete()\ndel C._qa_fixture\nresult=True")


if __name__ == '__main__':
    run_scenario('byok_claude_code_e2e', run)
