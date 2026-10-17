#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Local model names: real dialog, HTTP probe, save workers and relay.

Run on an isolated MIXAR_QA=1 app with QA_HARNESS and MIXAR_QA_PORT set.
No credits or real credentials. By default a loopback HTTP fixture returns
a synthetic path. Set MIXAR_QA_LLAMA_BASE and MIXAR_TEST_GGUF to exercise an
unaliased real llama-server; only the backend service and key store are faked.
MIXAR_QA_SOURCE_ROOT can load the reviewed Python modules into a built app.
Screenshots and the verdict go under QA_SCENARIO_OUT.
MIXAR_QA_BASELINE_ROOT can hold the target branch's detect.py and relay.py
to prove the unfixed behavior in the same app against the same real server.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', 'build/qa/model-name-privacy'))
OUT.mkdir(parents=True, exist_ok=True)
WM = 'bpy.data.window_managers[0]'
STATE = "bpy.app.driver_namespace['qa_model_privacy']"
BASENAME = Path(os.environ.get('MIXAR_TEST_GGUF', 'QA-Model.gguf')).name
HUB_ID = 'hf.co/qa/model:QA-Model.gguf'

SETUP = r'''
import bpy, os, json, threading, importlib
from pathlib import Path
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
assert os.environ.get('MIXAR_QA') == '1'
source = os.environ.get('MIXAR_QA_SOURCE_ROOT')
if source:
    for package in ('mixar.modules.local_models.core', 'mixar.modules.byok', 'mixar.modules.byok.core'):
        pkg = importlib.import_module(package)
        path = str(Path(source) / 'src/scripts' / package.replace('.', '/'))
        pkg.__path__ = [path, *[p for p in pkg.__path__ if p != path]]
    for name in ('byok.constants', 'local_models.core.model_name', 'local_models.core.detect',
                 'local_models.core.relay', 'local_models.core.server_supervisor',
                 'byok.core.byok_client', 'byok.core.local_provider'):
        importlib.reload(importlib.import_module('mixar.modules.' + name))
from mixar.modules.local_models.core import detect, relay, manifest, server_supervisor
from mixar.modules.byok.core import byok_client as B, local_provider as L
from mixar.modules.byok.core import preference_client as P
from mixar.modules.byok.core import credential_state as C
real_base = os.environ.get('MIXAR_QA_LLAMA_BASE')
path = os.environ['MIXAR_TEST_GGUF'] if real_base else r'C:\Users\qa-synthetic\AppData\models\QA-Model.gguf'
hub_id = 'hf.co/qa/model:QA-Model.gguf'
fixture = SimpleNamespace(path=path, hub_id=hub_id, saves=[], detected=None,
                          relayed=None, error=None, saved_model=None, raw_model=None,
                          before_detected=None, before_model=None)
fixture.originals = (B.get_agent_service, B._store_local_key if hasattr(B, '_store_local_key') else None,
                     P.get_agent_service, L.refresh_detected_async, relay.get_approved_bases(), C.snapshot())
fixture.registration = manifest.get_registered()
fixture.detected_before = list(L._detected)
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass
    def do_GET(self):
        body = json.dumps({'data': [{'id': path}, {'id': hub_id}]}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert request['model'] == 'QA-Model.gguf'
        body = json.dumps({'model': path, 'choices': [{'message': {'content': 'ok'}}]}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)
fixture.server = None
if real_base:
    fixture.base = real_base.rstrip('/')
else:
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    fixture.server = server
    fixture.base = f'http://127.0.0.1:{server.server_port}'
    threading.Thread(target=server.serve_forever, daemon=True).start()
def response(data):
    return SimpleNamespace(success=True, status_code=200, data={'data': data})
def payload():
    return {'byok_active': bool(fixture.saves), 'items': [
        {'provider': 'local', 'model': fixture.saved_model,
         'base_url': fixture.base, 'key_preview': '', 'supports_vision': False}
    ] if fixture.saves else []}
def save(**kwargs):
    assert kwargs['api_key'] is None
    fixture.saves.append(kwargs)
    fixture.saved_model = kwargs['model']
    return response(payload())
service = SimpleNamespace(save_credentials_all=save, get_credentials=lambda: response(payload()),
    get_model_preference=lambda: response({'byok_active': bool(fixture.saves), 'items': []}))
B.get_agent_service = P.get_agent_service = lambda: service
B._store_local_key = lambda *_args: True
L.refresh_detected_async = lambda: None
C.clear()
wm = bpy.data.window_managers[0]
wm.byok_form_local_detected = 'NONE'
wm.byok_form_local_custom_model = ''
wm.byok_form_local_custom_base = ''
bpy.app.driver_namespace['qa_model_privacy'] = fixture
def probe_and_relay():
    try:
        import urllib.request, urllib.parse
        port = urllib.parse.urlsplit(fixture.base).port
        fixture.detected = detect._probe_one('llama_cpp', port, 5)
        relay.set_approved_bases([fixture.base])
        body = json.dumps({'model': Path(path).name, 'max_tokens': 8,
            'temperature': 0, 'messages': [{'role': 'user', 'content': 'Say hello.'}]})
        if real_base:
            req = urllib.request.Request(fixture.base + '/v1/chat/completions',
                data=body.encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = json.load(response)
            fixture.raw_model = raw['model']
            assert fixture.raw_model == path, raw
            assert raw['usage']['completion_tokens'] > 0
            baseline = os.environ.get('MIXAR_QA_BASELINE_ROOT')
            if baseline:
                import importlib.util
                before = {}
                for name in ('detect', 'relay'):
                    spec = importlib.util.spec_from_file_location(
                        'mixar.modules.local_models.core.qa_before_' + name,
                        str(Path(baseline) / (name + '.py')))
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    before[name] = module
                fixture.before_detected = before['detect']._probe_one('llama_cpp', port, 5)['models']
                before['relay'].set_approved_bases([fixture.base])
                old_replies = []
                before['relay'].handle_llm_request({'method': 'POST',
                    'url': fixture.base + '/v1/chat/completions',
                    'headers': {'content-type': 'application/json'}, 'body': body}, old_replies.append)
                fixture.before_model = json.loads(old_replies[0]['body'])['model']
                assert fixture.before_detected == [path]
                assert fixture.before_model == path
        replies = []
        relay.handle_llm_request({'method': 'POST',
            'url': fixture.base + '/v1/chat/completions',
            'headers': {'content-type': 'application/json'},
            'body': body}, replies.append)
        fixture.relayed = replies[0]
    except Exception as exc:
        fixture.error = str(exc)
threading.Thread(target=probe_and_relay, daemon=True).start()
argv = server_supervisor.build_server_argv('llama-server', path, 11500, 'fixture', alias='qa-model')
assert argv[argv.index('--alias') + 1] == 'qa-model'
result = {'source': B.__file__, 'base': fixture.base, 'alias': 'qa-model',
          'gguf': path, 'real_inference': bool(real_base)}
'''

CLEANUP = '''
import threading
from mixar.modules.byok.core import byok_client as B, local_provider as L, preference_client as P
from mixar.modules.byok.core import credential_state as C
from mixar.modules.local_models.core import relay, manifest
f = bpy.app.driver_namespace.pop('qa_model_privacy')
B.get_agent_service, B._store_local_key, P.get_agent_service, L.refresh_detected_async, bases, cached = f.originals
relay.set_approved_bases(bases)
C.clear()
with C._lock:
    C._state = cached
C.apply_to_wm()
registered = f.registration or {}
manifest.set_registered(registered.get('base_url'), registered.get('model_id'), registered.get('supports_vision'))
L._apply_detected(f.detected_before)
def stop():
    if f.server is not None:
        f.server.shutdown()
        f.server.server_close()
threading.Thread(target=stop, daemon=True).start()
result = True
'''


def snap(qa, name):
    path = str(OUT / (name + '.png'))
    qa.step(name + '_snap', qa.cmd, 'snap', path=path,
            target={'op': 'MIXAR_BYOK_OT_save', 'popup': True}, margin=900)
    return path


def run(qa):
    qa.step('dismiss_splash', qa.dismiss_splash)
    setup = qa.step('install_isolated_fixture', qa.eval, SETUP)
    try:
        qa.wait(f'{STATE}.relayed is not None or {STATE}.error is not None', timeout=10)
        transport = qa.step('assert_probe_alias_and_response_privacy', qa.eval, f'''
from mixar.modules.byok.core import local_provider as L
f = {STATE}
assert f.error is None, f.error
expected = [{BASENAME!r}] if f.raw_model else [{BASENAME!r}, {HUB_ID!r}]
assert f.detected['models'] == expected, f.detected
reply = __import__('json').loads(f.relayed['body'])
assert reply['model'] == {BASENAME!r}, reply
if f.raw_model:
    assert reply['usage']['completion_tokens'] > 0
    assert 'AppData' in f.raw_model
else:
    assert reply['choices'][0]['message']['content'] == 'ok'
assert 'AppData' not in f.relayed['body']
L._apply_detected([f.detected])
result = {{'detected': f.detected['models'], 'response_model': reply['model'],
           'raw_model': f.raw_model, 'before_detected': f.before_detected,
           'before_response_model': f.before_model,
           'content': reply['choices'][0]['message']['content']}}
''')
        qa.step('open_provider_dialog', qa.eval,
                "result=str(bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT'))")
        qa.step('choose_local_provider', qa.cmd, 'choose',
                widget={'prop': 'byok_form_provider', 'popup': True}, item='Local (this computer)')
        # Mode is an expanded enum (two row buttons), not a dropdown.
        qa.step('choose_custom_server', qa.click,
                prop='byok_form_local_mode', text='Custom local server', popup=True)
        qa.step('select_detected_server', qa.cmd, 'choose',
                widget={'prop': 'byok_form_local_detected', 'popup': True},
                item='llama.cpp server — ' + setup['base'])
        qa.step('assert_detected_field', qa.eval,
                f'assert {WM}.byok_form_local_custom_model == {BASENAME!r}\nresult=True')
        before = snap(qa, 'detected_model_basename')
        # The typed-path route must be safe too. Keep the test path synthetic.
        qa.step('enter_synthetic_path', qa.cmd, 'set_text',
                widget={'prop': 'byok_form_local_custom_model', 'popup': True},
                text=setup['gguf'], enter=False)
        dialog_window = qa.find(op='MIXAR_BYOK_OT_save', popup=True)['widgets'][0]['window']
        qa.step('save_local_model', qa.click, op='MIXAR_BYOK_OT_save', popup=True)
        qa.wait(f"{WM}.byok_dialog_state in ('SAVED', 'ERROR')", timeout=15)
        saved = qa.step('assert_saved_model_and_manifest', qa.eval, f'''
from mixar.modules.local_models.core import manifest
f = {STATE}
wm = bpy.data.window_managers[0]
assert wm.byok_dialog_state == 'SAVED', wm.byok_last_error
assert len(f.saves) == 1
assert f.saves[0]['model'] == {BASENAME!r}, f.saves
assert manifest.get_registered()['model_id'] == {BASENAME!r}
assert wm.byok_current_model == {BASENAME!r}
result = {{'model': wm.byok_current_model, 'state': wm.byok_dialog_state}}
''')
        after_path = str(OUT / 'saved_model_basename.png')
        # Reopen to prove the persisted registration prefills a safe name.
        # This also avoids depending on older bundles' async popup redraw.
        qa.step('close_saved_dialog', qa.press, 'ESC', window=dialog_window)
        qa.step('reopen_saved_configuration', qa.eval,
                "result=str(bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT'))")
        qa.step('assert_reopened_name', qa.eval,
                f'assert {WM}.byok_form_local_custom_model == {BASENAME!r}\nresult=True')
        qa.step('saved_model_snap', qa.cmd, 'snap', path=after_path,
                target={'op': 'MIXAR_BYOK_OT_save', 'popup': True}, margin=900)
        qa.step('close_dialog', qa.click, text='Cancel', popup=True)
        return {'setup': setup, 'transport': transport, 'saved': saved,
                'screenshots': [before, after_path], 'real_inference': setup['real_inference']}
    finally:
        hits = qa.find(prop='byok_form_provider', popup=True)['widgets']
        if hits:
            qa.press('ESC', window=hits[0]['window'])
        qa.step('restore_fixture_boundaries', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('local_model_name_privacy_e2e', run)
