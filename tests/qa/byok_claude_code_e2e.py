#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay the real Claude form, sign-out failure, save, pause, resume and remove.

Use an isolated MIXAR_QA=1 app. The fixture replaces the credential store
in memory and stubs CLI/HTTP boundaries; native clicks, workers, callbacks,
record construction and state mirrors are real. No real account changes.
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
from mixar.modules.byok.ui.operators import byok_ops as O
from mixar.modules.byok.core import key_prompt as Q
assert os.environ.get('MIXAR_QA') == '1'
assert not B.mutation_in_flight()
f = SimpleNamespace(saved=[], state=S.snapshot(), preference=P.snapshot(), record=None,
                    puts=[], deletes=0)
C._qa_fixture = f
def patch(module, name, value):
    f.saved.append((module, name, getattr(module, name)))
    setattr(module, name, value)
def save(record, *args, **kwargs):
    f.record = dict(record)
    return True
def forget(*args, **kwargs):
    f.record = None
    return True
patch(K, 'load', lambda *a, **kw: dict(f.record) if f.record else None)
patch(K, 'save', save)
patch(K, 'delete', forget)
patch(K, 'current_user_id', lambda: 'qa-claude-provider')
patch(C, 'check_ready', lambda: None)
patch(P, 'refresh', lambda *a, **kw: None)
patch(S, 'refresh', lambda *a, **kw: None)
patch(O, '_deregister_local_if_switched_away', lambda *a: None)
patch(Q, 'notify_removed', lambda: None)
def put(provider, model, api_key, *args, **kw):
    assert provider == 'claude_code' and api_key is None
    f.puts.append({'provider': provider, 'model': model, 'api_key': api_key})
    return True, {'byok_active': True, 'items': [{'provider': provider, 'model': model, 'key_preview': 'Claude Code on this computer', 'supports_vision': True}]}, None
patch(B, '_put_sealed', put)
def delete():
    f.deletes += 1
    return SimpleNamespace(success=True, status_code=200, data={'data': {'removed': 1}})
patch(B, 'get_agent_service', lambda: SimpleNamespace(delete_credentials_all=delete))
def signed_out(model):
    raise C.ClaudeCodeError('claude_login_required', 'Run claude auth login in your terminal, then Save & Activate.')
patch(C, 'validate_model', signed_out)
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
        qa.eval("from mixar.modules.byok.core import claude_code as C\nC.validate_model=lambda model: None\nresult=True")
        qa.step('save_signed_in', qa.click, op='MIXAR_BYOK_OT_save', popup=True)
        qa.wait("bpy.context.window_manager.byok_dialog_state=='SAVED'", timeout=10)
        record = qa.eval("from mixar.modules.byok.core import key_store as K\nr=K.load()\nassert r['provider']=='claude_code' and r['key'] is None\nresult=r")
        qa.snap(str(OUT / 'saved.png'))
        close(qa)
        qa.wait("bpy.context.window_manager.byok_key_resumable", timeout=10)
        qa.eval("from mixar.modules.byok.ui.operators import byok_toggle_ops as T\n"
                "assert T.pause(bpy.context.window_manager)\nresult=True")
        qa.step('pause_keeps_device_record', qa.wait,
                "not bpy.context.window_manager.byok_is_active and "
                "not __import__('mixar.modules.byok.core.byok_client',fromlist=['x']).mutation_in_flight() and "
                "__import__('mixar.modules.byok.core.claude_code',fromlist=['x'])._qa_fixture.deletes==1", timeout=10)
        qa.eval("from mixar.modules.byok.core import key_store as K\n"
                "assert K.load()['provider']=='claude_code'\nresult=True")
        qa.open_chat()
        qa.snap(str(OUT / 'paused.png'))
        qa.eval("from mixar.modules.byok.ui.operators import byok_toggle_ops as T\n"
                "assert T.resume(bpy.context.window_manager)\nresult=True")
        qa.step('resume_keyless_provider', qa.wait,
                "bpy.context.window_manager.byok_is_active and "
                "not __import__('mixar.modules.byok.core.byok_client',fromlist=['x']).mutation_in_flight()", timeout=10)
        puts = qa.eval("from mixar.modules.byok.core import claude_code as C\nresult=C._qa_fixture.puts")
        assert len(puts) == 2 and all(p['api_key'] is None for p in puts)
        qa.eval("win=drv.main_window()\narea=max(win.screen.areas,key=lambda a:a.width*a.height)\nwith bpy.context.temp_override(window=win,area=area):\n bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT')\nresult=True")
        qa.wait("bool(drv.find(op='MIXAR_BYOK_OT_request_remove',popup=True))", timeout=10)
        qa.step('request_remove', qa.click, op='MIXAR_BYOK_OT_request_remove', popup=True)
        qa.wait("bool(drv.find(op='MIXAR_BYOK_OT_confirm_remove',popup=True))", timeout=10)
        qa.step('confirm_remove', qa.click, op='MIXAR_BYOK_OT_confirm_remove', popup=True)
        qa.wait("bpy.context.window_manager.byok_dialog_state=='REMOVED'", timeout=10)
        qa.eval("from mixar.modules.byok.core import key_store as K,claude_code as C\n"
                "assert K.load() is None and C._qa_fixture.deletes==2\nresult=True")
        qa.snap(str(OUT / 'removed.png'))
        return {'record': record, 'puts': puts, 'deletes': 2,
                'snaps': [str(OUT / n) for n in ('setup.png','login-required.png','saved.png','paused.png','removed.png')]}
    finally:
        close(qa)
        qa.wait("not __import__('mixar.modules.byok.core.byok_client',fromlist=['x']).mutation_in_flight()", timeout=10)
        qa.eval("from mixar.modules.byok.core import claude_code as C,credential_state as S,preference_state as P\n"
                "f=C._qa_fixture\nS.clear()\nS._state=dict(f.state)\nS.apply_to_wm()\n"
                "P.apply_local(f.preference)\n"
                "for module,name,value in reversed(f.saved):setattr(module,name,value)\n"
                "del C._qa_fixture\nresult=True")


if __name__ == '__main__':
    run_scenario('byok_claude_code_e2e', run)
