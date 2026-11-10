# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux must diagnose an unusable keyring before a successful browser login."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mixar.config import config
from mixar.modules.auth.core import sso, storage_health


@pytest.fixture
def store(monkeypatch):
    entries = {'AccessToken': 'old-access', 'RefreshToken': 'old-refresh'}
    fake = SimpleNamespace(
        set_secret=Mock(side_effect=lambda k, v: entries.__setitem__(k, v) or True),
        get_secret=Mock(side_effect=entries.get),
        delete_secret=Mock(side_effect=lambda k: entries.pop(k, None) is not None),
    )
    monkeypatch.setattr(storage_health, 'credential_store', fake)
    monkeypatch.setattr(sso.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(config, 'get_dev_bypass_credentials', lambda: (None, None))
    return fake, entries


def test_probe_round_trip_preserves_existing_tokens(store):
    fake, entries = store
    assert storage_health.check_login_storage()
    assert entries == {'AccessToken': 'old-access', 'RefreshToken': 'old-refresh'}
    assert fake.delete_secret.call_args == fake.get_secret.call_args


@pytest.mark.parametrize('failure', ['write', 'read', 'delete'])
def test_storage_failure_prevents_browser_and_allows_retry(store, monkeypatch, failure):
    fake, entries = store
    method = getattr(fake, {'write': 'set_secret', 'read': 'get_secret', 'delete': 'delete_secret'}[failure])
    original = method.side_effect
    method.side_effect = None
    method.return_value = None if failure == 'read' else False
    browser = Mock()
    listener = Mock()
    monkeypatch.setattr(sso.webbrowser, 'open', browser)
    monkeypatch.setattr(sso, 'start_callback_server', listener)
    result = sso.sso_login()
    assert not result['success']
    assert result['failure_kind'] == 'credential_storage'
    assert 'Secret Service' in result['message'] and 'D-Bus' in result['message']
    browser.assert_not_called()
    listener.assert_not_called()
    assert entries['AccessToken'] == 'old-access'
    assert entries['RefreshToken'] == 'old-refresh'
    assert fake.delete_secret.called
    method.side_effect = original
    assert storage_health.check_login_storage()  # no stale failure cache


def test_failure_after_browser_callback_has_actionable_error(store, monkeypatch):
    server = Mock(server_address=('127.0.0.1', 54321))
    monkeypatch.setattr(sso, 'start_callback_server', lambda state: server)
    monkeypatch.setattr(sso.webbrowser, 'open', lambda url: True)
    monkeypatch.setattr(sso, 'wait_for_code', lambda *a, **kw: 'code')
    monkeypatch.setattr(sso, '_exchange_code', lambda *a: (
        {'access_token': 'new-access', 'refresh_token': 'new-refresh'}, None))
    monkeypatch.setattr(sso, 'store_login_token_pair', lambda *a: (False, 'Failed to store refresh token'))
    result = sso.sso_login()
    assert result == storage_health.storage_error_result()
    server.server_close.assert_called_once()


@pytest.mark.parametrize('error', [ImportError('backend missing'), PermissionError('read-only config')])
def test_real_store_errors_become_preflight_failure(monkeypatch, error):
    import sys
    from mixar.modules.common.utils import credential_store

    def fail(*args):
        raise error

    monkeypatch.setattr(credential_store, '_IS_WINDOWS', False)
    monkeypatch.setattr(credential_store, '_IS_MACOS', False)
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(
        set_password=fail, get_password=fail, delete_password=fail,
        errors=SimpleNamespace(PasswordDeleteError=LookupError)))
    assert not storage_health.check_login_storage()


def test_usable_storage_completes_login(store, monkeypatch):
    server = Mock(server_address=('127.0.0.1', 54321))
    monkeypatch.setattr(sso, 'start_callback_server', lambda state: server)
    monkeypatch.setattr(sso.webbrowser, 'open', lambda url: True)
    monkeypatch.setattr(sso, 'wait_for_code', lambda *a, **kw: 'code')
    monkeypatch.setattr(sso, '_exchange_code', lambda *a: (
        {'access_token': 'new-access', 'refresh_token': 'new-refresh'}, None))
    save_pair = Mock(return_value=(True, None))
    monkeypatch.setattr(sso, 'store_login_token_pair', save_pair)
    assert sso.sso_login()['success']
    save_pair.assert_called_once_with('new-access', 'new-refresh')
    server.server_close.assert_called_once()


def test_expired_session_does_not_hide_storage_error():
    from mixar.modules.space_mixie_chat.ui.login_panel import draw_login_feedback

    layout = Mock()
    wm = SimpleNamespace(mixie_chat_session_expired=True,
                         mixie_chat_login_error=storage_health.storage_error_result()['message'])
    draw_login_feedback(layout, wm)
    labels = layout.box.return_value.column.return_value.label.call_args_list
    text = ' '.join(call.kwargs.get('text', '') for call in labels)
    assert 'Secret Service' in text and 'D-Bus' in text
    layout.box.return_value.label.assert_not_called()
