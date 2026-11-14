# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native evidence must fail closed on denied, stale or malformed captures."""
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def capture():
    path = Path(__file__).parent / 'qa' / 'mac_native_ui_capture.py'
    spec = importlib.util.spec_from_file_location('qa_mac_capture_contract', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observation():
    return {'identity': {'pid': 41}, 'window': {'number': 12, 'bounds_points': [5, 7, 100, 50],
                                              'backing_scale': 2}, 'screen_capture_preflight': False}


def receipt(path):
    return json.loads(path.with_suffix('.capture.json').read_text())


@pytest.mark.parametrize('error', [None, subprocess.TimeoutExpired('screencapture', 2)])
def test_denied_or_timed_out_capture_is_never_available(capture, monkeypatch, tmp_path, error):
    def run(command, **kwargs):
        assert command[:5] == ['/usr/sbin/screencapture', '-x', '-o', '-l', '12']
        assert kwargs['timeout'] == 2
        if error:
            raise error
        return SimpleNamespace(returncode=1, stderr='could not create image from window')

    monkeypatch.setattr(capture.subprocess, 'run', run)
    path = tmp_path / 'denied.png'
    capture._capture(path, observation(), 2)
    assert capture.status()['done'] and not capture.status()['available']
    assert receipt(path)['error'] and not receipt(path)['available']
    assert not path.exists()


@pytest.mark.parametrize('size,valid', [((200, 100), True), ((100, 50), False)])
def test_png_must_match_native_retina_window(capture, monkeypatch, tmp_path, size, valid):
    from PIL import Image

    def run(command, **kwargs):
        Image.new('RGBA', size, (25, 25, 25, 255)).save(command[-1])
        return SimpleNamespace(returncode=0, stderr='')

    monkeypatch.setattr(capture.subprocess, 'run', run)
    path = tmp_path / 'retina.png'
    capture._capture(path, observation(), 2)
    result = receipt(path)
    assert result['available'] is valid
    if valid:
        assert result['size'] == [200, 100] and len(result['sha256']) == 64
        # A false app preflight does not alone decide an actual PNG result.
        assert result['screen_capture_preflight'] is False
    else:
        assert 'dimensions' in result['error']


def test_exit_zero_without_png_is_not_capture_success(capture, monkeypatch, tmp_path):
    monkeypatch.setattr(capture.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stderr=''))
    path = tmp_path / 'missing.png'
    capture._capture(path, observation(), 2)
    assert not receipt(path)['available']
    assert 'regular file' in receipt(path)['error']


def test_window_change_after_capture_is_not_accepted(capture, monkeypatch):
    before = observation()
    capture._state = dict(before, done=True, available=True)
    after = observation()
    after['window']['number'] = 99
    monkeypatch.setattr(capture, 'observe', lambda *a: after)
    with pytest.raises(AssertionError, match='window changed'):
        capture.verify_stable({'pid': 41})


def test_controller_denial_stops_before_any_app_observation(capture, monkeypatch, tmp_path):
    class Preflight:
        def __call__(self):
            return False

    monkeypatch.setattr(capture.sys, 'platform', 'darwin')
    monkeypatch.setattr(capture.ct, 'CDLL', lambda _: SimpleNamespace(CGPreflightScreenCaptureAccess=Preflight()))

    class App:
        def eval(self, code):
            pytest.fail('permission-denied controller must not touch app')

    with pytest.raises(AssertionError, match='Screen Recording unavailable'):
        capture.capture_controller(App(), tmp_path/'forbidden.png', {'pid': 41})
    assert not list(tmp_path.iterdir())
