# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The local Claude CLI owns sign-in; Mixar tools never execute in its process."""
import json
from unittest.mock import Mock

import pytest
from mixar.modules.byok.core import claude_code as C, key_store, model_suggestions as M


def request(**kw):
    return dict(mode=C.MODE, model='claude-test', messages=[{'role': 'human', 'content': 'hello'}], tools=[], **kw)


def test_sign_in_uses_cli_status_not_credential_files(monkeypatch):
    run = Mock(return_value=json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'}))
    monkeypatch.setattr(C, '_run', run)
    C.check_ready()
    assert run.call_args.args == (['auth', 'status', '--json'],)
    run.return_value = json.dumps({'loggedIn': False, 'authMethod': 'none'})
    with pytest.raises(C.ClaudeCodeError, match='claude auth login'):
        C.check_ready()
    run.return_value = json.dumps({'loggedIn': True, 'authMethod': 'api_key'})
    with pytest.raises(C.ClaudeCodeError):
        C.check_ready()


def test_inference_is_stateless_and_cli_has_no_tools_or_mcp(monkeypatch):
    monkeypatch.setattr(C, 'check_ready', lambda: None)
    run = Mock(return_value=json.dumps({'type': 'result', 'structured_output': {'content': 'hello', 'tool_calls': []}, 'usage': {'output_tokens': 2}}))
    monkeypatch.setattr(C, '_run', run)
    assert C.infer(request())['output']['content'] == 'hello'
    args, payload = run.call_args.args
    assert args[args.index('--tools') + 1] == ''
    assert '--safe-mode' in args and '--no-session-persistence' in args and '--strict-mcp-config' in args
    assert json.loads(payload)['message']['content'][0]['type'] == 'text'
    assert '--dangerously-skip-permissions' not in args


def test_inline_images_survive_and_remote_urls_are_refused():
    params = request()
    params['messages'][0]['content'] = [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,YQ=='}}]
    content = json.loads(C._prompt(params))['message']['content']
    assert content[1] == {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'YQ=='}}
    params['messages'][0]['content'][0]['image_url']['url'] = 'http://169.254.169.254/credentials'
    with pytest.raises(C.ClaudeCodeError):
        C._prompt(params)


def test_no_device_grant_never_starts_subprocess(monkeypatch):
    from mixar.modules.byok.core import credential_state
    monkeypatch.setattr(credential_state, 'snapshot', lambda: {})
    monkeypatch.setattr(key_store, 'load', lambda: None)
    infer = Mock()
    monkeypatch.setattr(C, 'infer', infer)
    replies = []
    C.handle_request(request(), replies.append)
    assert replies == [{'error': {'code': 'claude_not_enabled'}}]
    infer.assert_not_called()


def test_keyless_record_and_resume_store_no_claude_tokens(monkeypatch):
    record = key_store.make_record('claude_code', 'MUST-NOT-STORE', model='claude-test')
    assert record['key'] is None
    monkeypatch.setattr(C, 'check_ready', lambda: None)
    assert key_store.materialize(record) == (record, None)
    assert key_store.resumable_summary(record) == {'provider': 'claude_code', 'model': 'claude-test'}


def test_catalog_models_and_thinking_come_from_anthropic():
    M.populate_from_payload({'providers': [{'id': 'anthropic', 'label': 'Claude API', 'models': [{'id': 'claude-test', 'label': 'Claude Test', 'thinking_levels': ['low', 'high']}]}]})
    try:
        assert M.is_valid_model('claude_code', 'claude-test')
        assert M.thinking_levels('claude_code', 'claude-test') == ['low', 'high']
        assert 'claude_code' in {p[0] for p in M.get_provider_items()}
    finally:
        M.clear()


def test_model_cannot_inject_command_line_options(monkeypatch):
    run = Mock()
    monkeypatch.setattr(C, '_run', run)
    params = request()
    params['model'] = 'claude --tools Bash'
    with pytest.raises(C.ClaudeCodeError):
        C.infer(params)
    run.assert_not_called()


def test_save_probes_selected_model_through_same_inference_path(monkeypatch):
    infer = Mock(return_value={'output': {'content': 'Connected.', 'tool_calls': []}})
    monkeypatch.setattr(C, 'infer', infer)
    C.validate_model('claude-test')
    params = infer.call_args.args[0]
    assert params['model'] == 'claude-test'
    assert params['tools'] == [] and params['tool_choice'] == 'none'


@pytest.mark.parametrize("block", [
    {"type": "image", "source_type": "base64", "data": "YQ==", "mime_type": "image/png"},
    {"type": "image", "base64": "YQ==", "mime_type": "image/png"},
])
def test_langchain_viewed_image_is_native_cli_image_and_not_json_text(block):
    params = request()
    params['messages'][0]['content'] = [{'type': 'text', 'text': 'Compare this reference'}, block]
    content = json.loads(C._prompt(params))['message']['content']
    assert content[1] == {'type': 'image', 'source': {
        'type': 'base64', 'media_type': 'image/png', 'data': 'YQ=='}}
    assert 'YQ==' not in content[0]['text']
    assert '[Attached image 1]' in content[0]['text']
    assert block.get('data', block.get('base64')) == 'YQ=='  # history is untouched


def test_eight_concurrent_requests_all_start_without_a_local_process_cap(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from mixar.modules.byok.core import credential_state
    monkeypatch.setattr(credential_state, 'snapshot', lambda: {
        'byok_is_active': True, 'byok_current_provider': 'claude_code'})
    monkeypatch.setattr(key_store, 'load', lambda: {'provider': 'claude_code'})
    started = threading.Barrier(8, timeout=5)
    def infer(params):
        started.wait()  # Every request must enter inference before any finishes.
        return {'output': {'content': 'Done', 'tool_calls': []}}
    monkeypatch.setattr(C, 'infer', infer)
    replies = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: C.handle_request(request(), replies.append), range(8)))
    assert len(replies) == 8
    assert all(reply.get('output', {}).get('content') == 'Done' for reply in replies)
