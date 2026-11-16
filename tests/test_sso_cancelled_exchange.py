# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""AUTH-10: a sign-in cancelled (or superseded) while its token exchange is
in flight must never install its pair, even after a newer login landed."""
import threading
from unittest.mock import Mock

import pytest

from mixar.config import config
from mixar.modules.auth.core import auth, sso


@pytest.fixture
def keyring(monkeypatch):
    pair = {'access': 'old-access', 'refresh': 'old-refresh'}
    writes = []

    def store(kind):
        def _write(token):
            writes.append((kind, token))
            pair[kind] = token
            return True
        return _write

    monkeypatch.setattr(auth, 'store_access_token', store('access'))
    monkeypatch.setattr(auth, 'store_refresh_token', store('refresh'))
    monkeypatch.setattr(auth, '_credentials_snapshot', lambda: (pair['access'], pair['refresh']))
    monkeypatch.setattr(auth, '_clear_refresh_state_locked', lambda: True)
    monkeypatch.setattr(config, 'get_dev_bypass_credentials', lambda: (None, None))
    monkeypatch.setattr(sso.platform, 'system', lambda: 'Darwin')
    return pair, writes


def test_a_cancelled_attempt_cannot_store_its_pair(keyring):
    pair, writes = keyring
    cancel = threading.Event()
    cancel.set()
    assert auth.store_login_token_pair('stale-access', 'stale-refresh', cancel=cancel) == (False, None)
    assert writes == [] and pair == {'access': 'old-access', 'refresh': 'old-refresh'}


def test_an_exchange_cancelled_in_flight_never_replaces_the_newer_login(keyring, monkeypatch):
    pair, writes = keyring
    cancel = threading.Event()
    server = Mock(server_address=('127.0.0.1', 54321))
    monkeypatch.setattr(sso, 'start_callback_server', lambda state: server)
    monkeypatch.setattr(sso.webbrowser, 'open', lambda url: True)
    monkeypatch.setattr(sso, 'wait_for_code', lambda *a, **kw: 'code')

    def exchange(*_):
        # The user cancels, then a newer sign-in stores its own pair, all
        # while this attempt's exchange request is still on the wire.
        cancel.set()
        assert auth.store_login_token_pair('latest-access', 'latest-refresh')[0]
        return {'access_token': 'stale-access', 'refresh_token': 'stale-refresh'}, None

    monkeypatch.setattr(sso, '_exchange_code', exchange)
    result = sso.sso_login(cancel=cancel)

    assert result['success'] is False and result['cancelled'] is True
    assert pair == {'access': 'latest-access', 'refresh': 'latest-refresh'}
    assert ('access', 'stale-access') not in writes


def test_an_uncancelled_attempt_still_signs_in(keyring, monkeypatch):
    pair, _ = keyring
    server = Mock(server_address=('127.0.0.1', 54321))
    monkeypatch.setattr(sso, 'start_callback_server', lambda state: server)
    monkeypatch.setattr(sso.webbrowser, 'open', lambda url: True)
    monkeypatch.setattr(sso, 'wait_for_code', lambda *a, **kw: 'code')
    monkeypatch.setattr(sso, '_exchange_code', lambda *a: (
        {'access_token': 'new-access', 'refresh_token': 'new-refresh'}, None))
    assert sso.sso_login(cancel=threading.Event())['success']
    assert pair == {'access': 'new-access', 'refresh': 'new-refresh'}


def test_a_storage_failure_during_a_cancel_reports_the_storage_failure(keyring, monkeypatch):
    """The keyring fails while the user is cancelling: the user needs the
    storage error (it blocks every later sign-in), not "cancelled"."""
    cancel = threading.Event()
    server = Mock(server_address=('127.0.0.1', 54321))
    monkeypatch.setattr(sso, 'start_callback_server', lambda state: server)
    monkeypatch.setattr(sso.webbrowser, 'open', lambda url: True)
    monkeypatch.setattr(sso, 'wait_for_code', lambda *a, **kw: 'code')
    monkeypatch.setattr(sso, '_exchange_code', lambda *a: (
        {'access_token': 'new-access', 'refresh_token': 'new-refresh'}, None))

    def failing_store(*_a, **_kw):
        cancel.set()  # the click lands while the keyring write is failing
        return False, 'Failed to store refresh token'

    monkeypatch.setattr(sso, 'store_login_token_pair', failing_store)
    result = sso.sso_login(cancel=cancel)
    assert result == {'success': False, 'message': 'Failed to store refresh token'}
