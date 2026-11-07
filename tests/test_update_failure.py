# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Updater failures retain diagnostics across worker/main-thread delivery."""
import sys
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault('mixar.modules.common.utils.mixie_space_utils', MagicMock())
from mixar.modules.common.updates.constants import InstallState
from mixar.modules.common.updates.core import install_flow, installer
from mixar.modules.common.updates.core.state import UpdateInfo, get_update_state


def _info():
    return UpdateInfo(latest_version='3.4.0', current_version='3.3.6',
                      download_url='https://cdn.example.com/installer.msi',
                      download_sha256='a' * 64, installer_type='msi')


def setup_function():
    get_update_state().set_idle()
    install_flow._cancel.clear()


@pytest.mark.parametrize('fault,reason', [
    ('network', 'network_error'), ('checksum', 'checksum_mismatch'),
    ('signature', 'signature_mismatch'), ('staging', 'permission_denied'),
])
def test_worker_failure_event_snapshots_attempt(monkeypatch, tmp_path, fault, reason):
    import urllib.error
    from mixar.modules.common.analytics import update_events
    from mixar.modules.common.updates.core import download, verify

    info = _info()
    state = get_update_state()
    state.set_available(info)
    state.set_downloading()
    callbacks, events = [], []
    monkeypatch.setattr(install_flow, '_on_main_thread', callbacks.append)
    monkeypatch.setattr(update_events, 'capture', lambda event, props, **kw: events.append((event, props)))
    path = str(tmp_path / 'installer')
    def prepare(*args):
        if fault == 'staging':
            raise PermissionError(13, 'private path', '/private/user')
        return path
    monkeypatch.setattr(install_flow, '_prepare_staging', prepare)
    monkeypatch.setattr(download, 'DOWNLOAD_RETRY_BACKOFF_S', 0)
    def serve(*args, **kwargs):
        if fault == 'network':
            raise urllib.error.URLError('private signed URL')
        import io
        response = io.BytesIO(b'installer')
        response.headers = {'Content-Length': '9'}
        return response
    monkeypatch.setattr(download.urllib.request, 'urlopen', serve)
    if fault == 'signature':
        import hashlib
        info.download_sha256 = hashlib.sha256(b'installer').hexdigest()
    monkeypatch.setattr(verify, 'verify_installer', lambda *a, **k: (verify.REJECTED, 'private path', ''))
    install_flow._worker(info, installer.Eligibility(True, extension='.msi'), '')
    assert state.install_state is InstallState.FAILED
    # A retry/state reset before the main-thread delivery must not rewrite history.
    state.set_idle()
    callbacks[0]()
    assert len(events) == 1
    name, props = events[0]
    assert name == 'update.download_finished'
    assert props['outcome'] == 'failed'
    assert props['target_version'] == info.latest_version
    assert props['reason_code'] == reason
    assert props['error_detail']
    assert 'private' not in str(props)


def test_failed_download_can_be_retried(monkeypatch):
    state = get_update_state()
    info = _info()
    state.set_available(info)
    state.set_install_failed('Download failed')
    calls = []
    def start(value):
        calls.append(value)
        state.set_downloading()
        return True
    monkeypatch.setattr(install_flow, 'start_download', start)
    assert install_flow.plan_restart() == 'waiting'
    assert calls == [info]
    assert state.install_requested


def test_unclassifiable_failure_still_reaches_the_ui_step(monkeypatch):
    """Diagnostics run inside the worker's except block: if they raised, the
    thread would escape and the "download finished" step would never run."""
    from mixar.modules.common.analytics import update_events

    class Odd(Exception):
        @property
        def reason_code(self):
            raise RuntimeError('diagnostics broke')

    def prepare(*args):
        raise Odd()

    info = _info()
    state = get_update_state()
    state.set_available(info)
    state.set_downloading()
    callbacks, events = [], []
    monkeypatch.setattr(install_flow, '_on_main_thread', callbacks.append)
    monkeypatch.setattr(update_events, 'capture', lambda event, props, **kw: events.append(props))
    monkeypatch.setattr(install_flow, '_prepare_staging', prepare)
    install_flow._worker(info, installer.Eligibility(True, extension='.msi'), '')
    assert state.install_state is InstallState.FAILED
    assert install_flow._after_download in callbacks
    callbacks[0]()
    assert events[0]['outcome'] == 'failed'
    assert events[0]['reason_code'] == 'unexpected_error'


@pytest.mark.parametrize('fault,retryable', [
    ('network', True), ('permission', True), ('checksum', False),
    ('signature', False), ('disk_full', False), ('read_only', False),
])
def test_retry_is_offered_only_when_a_fresh_download_can_fix_it(monkeypatch, tmp_path, fault, retryable):
    import errno
    import hashlib
    import io
    import urllib.error
    from mixar.modules.common.updates.core import download, verify

    info = _info()
    payload = b'installer'
    if fault == 'signature':
        info.download_sha256 = hashlib.sha256(payload).hexdigest()
    state = get_update_state()
    state.set_available(info)
    state.set_downloading()
    monkeypatch.setattr(install_flow, '_on_main_thread', lambda fn: None)
    monkeypatch.setattr(install_flow, '_prepare_staging', lambda *a: str(tmp_path / 'installer'))
    monkeypatch.setattr(download, 'DOWNLOAD_RETRY_BACKOFF_S', 0)
    numbers = {'permission': errno.EACCES, 'disk_full': errno.ENOSPC, 'read_only': errno.EROFS}
    if fault in numbers:
        def fail_open(*args):
            raise OSError(numbers[fault], 'no')
        monkeypatch.setattr(download._shared, '_open_part', fail_open)

    def serve(*args, **kwargs):
        if fault == 'network':
            raise urllib.error.URLError('down')
        response = io.BytesIO(payload)
        response.headers = {'Content-Length': str(len(payload))}
        return response
    monkeypatch.setattr(download.urllib.request, 'urlopen', serve)
    monkeypatch.setattr(verify, 'verify_installer', lambda *a, **k: (verify.REJECTED, '', ''))
    install_flow._worker(info, installer.Eligibility(True, extension='.msi'), '')
    assert state.install_state is InstallState.FAILED

    calls = []
    def start(value):
        calls.append(value)
        state.set_downloading()
        return True
    monkeypatch.setattr(install_flow, 'start_download', start)
    assert install_flow.plan_restart() == ('waiting' if retryable else 'browser')
    assert calls == ([info] if retryable else [])
