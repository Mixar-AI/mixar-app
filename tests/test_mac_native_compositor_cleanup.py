# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Controller ownership and restoration checks, not native pixel verdicts."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def native(monkeypatch):
    path = Path(__file__).parent / 'qa' / 'mac_native_compositor_e2e.py'
    monkeypatch.setenv('QA_HARNESS', '/unneeded-test-harness')
    monkeypatch.setitem(sys.modules, 'lib', SimpleNamespace(run_scenario=None))
    monkeypatch.setitem(sys.modules, 'mac_native_ui_capture', SimpleNamespace(capture_controller=None))
    spec = importlib.util.spec_from_file_location('qa_native_compositor_unit', path)
    module = importlib.util.module_from_spec(spec)
    original_path = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
    return module


def test_wrong_identity_stops_before_fixture_setup(native, monkeypatch):
    class Permission:
        def __call__(self):
            return True
    monkeypatch.setattr(native.sys, 'platform', 'darwin')
    monkeypatch.setattr(native.ct, 'CDLL', lambda *a: SimpleNamespace(CGPreflightScreenCaptureAccess=Permission()))
    monkeypatch.setenv('QA_RELEASE_IDENTITY', '{"pid": 10}')
    calls = []
    class WrongApp:
        def eval(self, code):
            calls.append(code)
            assert 'ns["_identity"]' in code
            raise RuntimeError('wrong QA process')
    with pytest.raises(RuntimeError, match='wrong QA process'):
        native.run(WrongApp())
    assert len(calls) == 1


def test_failed_handler_removal_still_restores_draft_hover_and_frames(native, monkeypatch):
    calls = []
    monkeypatch.setattr(native, '_identity', lambda *a: None)
    monkeypatch.setattr(native, '_settle', lambda *a: None)
    monkeypatch.setattr(native, '_frame', lambda *a: calls.append('restore-frame') or True)
    class App:
        def eval(self, code):
            calls.append(code)
            if "module=ns.get('bands')" in code:
                raise RuntimeError('band removal failed')
            return True
        def island_minimise(self):
            calls.append('minimise')
        def open_chat(self):
            calls.append('open')
    result = native._cleanup(App(), {}, {'draft': 'keep me', 'hover': True},
                             {'pill': [0, 0, 80, 30], 'island': [0, 0, 200, 200]})
    assert not result['ok']
    assert [row['ok'] for row in result['operations']] == [False, True, True, True, True, True, True]
    assert calls.count('restore-frame') == 2
    assert any('keep me' in call for call in calls)
    assert any('hover_ops.register()' in call for call in calls)
    assert not any('driver_namespace.pop(' in call for call in calls)
