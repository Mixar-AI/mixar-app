# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Failure-path checks for the manual fixture, never simulated UI verdicts."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def manual(monkeypatch):
    path = Path(__file__).parent / 'qa' / 'mac_manual_native_ui_e2e.py'
    spec = importlib.util.spec_from_file_location('qa_mac_manual_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    return module


def fail(message):
    raise RuntimeError(message)


def test_independent_restorations_continue_after_each_failure(manual):
    completed = []
    operations = [('bands', lambda: fail('draw handler removal failed')),
                  ('solid', lambda: completed.append('solid')),
                  ('frame', lambda: fail('window no longer visible')),
                  ('hover', lambda: completed.append('hover'))]
    rows = manual.attempt_all(operations)
    assert completed == ['solid', 'hover']
    assert [row['ok'] for row in rows] == [False, True, False, True]
    assert 'draw handler' in rows[0]['error'] and 'visible' in rows[2]['error']


def test_wrong_identity_stops_before_staging_or_cleanup(manual, monkeypatch, tmp_path):
    monkeypatch.setattr(manual, 'identity_check', lambda *args: fail('wrong QA process'))
    monkeypatch.setattr(manual, 'stage_view', lambda *args: pytest.fail('must not mutate'))
    monkeypatch.setattr(manual, 'cleanup', lambda *args: pytest.fail('must not mutate'))
    with pytest.raises(RuntimeError, match='wrong QA process'):
        manual.record_stage(None, None, {}, 'blue', None, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('failure_phase', ['observation', 'capture'])
def test_evidence_failure_restores_fixture_and_leaves_receipt(
        manual, monkeypatch, tmp_path, failure_phase):
    events = []
    monkeypatch.setattr(manual, 'identity_check', lambda *a: events.append('identity'))
    monkeypatch.setattr(manual, 'stage_view', lambda *a: events.append('stage') or 'blue')

    def observe(*args):
        events.append('observation')
        if failure_phase == 'observation':
            fail('observation failed')
        return {'window': {}}

    def capture(*args):
        events.append('capture')
        fail('capture failed')

    monkeypatch.setattr(manual, 'observation', observe)
    monkeypatch.setattr(manual, 'cleanup', lambda *a: events.append('cleanup') or {'ok': True})
    fixture = SimpleNamespace(_material=lambda _: None)
    with pytest.raises(RuntimeError, match=f'{failure_phase} failed'):
        manual.record_stage(None, fixture, {}, 'blue', capture, tmp_path)
    assert events[:2] == ['identity', 'stage'] and events[-1] == 'cleanup'
    receipt = json.loads((tmp_path / 'blue.json').read_text())
    assert receipt['cleanup_after_failure']['ok']
    assert f'{failure_phase} failed' in receipt['error']
    assert receipt['automatic_native_capture'] is False


def test_cleanup_stage_restores_before_observation_can_fail(manual, monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(manual, 'identity_check', lambda *a: events.append('identity'))
    monkeypatch.setattr(manual, 'cleanup', lambda *a: events.append('cleanup') or {'ok': True})

    def observe(*args):
        events.append('observation')
        fail('observation unavailable')

    monkeypatch.setattr(manual, 'observation', observe)
    with pytest.raises(RuntimeError, match='observation unavailable'):
        manual.record_stage(None, None, {}, 'cleanup', None, tmp_path)
    assert events == ['identity', 'cleanup', 'observation']
    receipt = json.loads((tmp_path / 'cleanup.json').read_text())
    assert receipt['cleanup']['ok'] and receipt['manual_screenshot'] == 'not_requested'


def test_cleanup_failure_cannot_hide_original_failure(manual, monkeypatch, tmp_path):
    monkeypatch.setattr(manual, 'identity_check', lambda *a: None)
    monkeypatch.setattr(manual, 'stage_view', lambda *a: fail('original staging error'))
    monkeypatch.setattr(manual, 'cleanup', lambda *a: fail('cleanup transport lost'))
    with pytest.raises(RuntimeError, match='original staging error'):
        manual.record_stage(None, None, {}, 'blue', None, tmp_path)
    receipt = json.loads((tmp_path / 'blue.json').read_text())
    assert 'original staging error' in receipt['error']
    assert receipt['cleanup_after_failure']['ok'] is False
    assert 'cleanup transport lost' in receipt['cleanup_after_failure']['error']
