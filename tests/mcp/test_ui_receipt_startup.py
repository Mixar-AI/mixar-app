# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Locked receipt journals must never block startup or bypass durable admission."""

import sqlite3
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from mixar.modules.common.ui_control.core import receipt_startup, receipts, service
from mixar.modules.common.ui_control.constants import UIError


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    pytest.fail('Receipt worker did not reach its expected state')


def test_locked_real_journal_returns_immediately_then_recovers(tmp_path):
    path = tmp_path / 'receipts.sqlite'
    original = receipts.Receipts(path)
    call = str(uuid4())
    digest = original.digest('scene', 'tool', {})
    original.claim(call, digest)
    original.finish(call, 'succeeded')
    original.close()
    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute('BEGIN IMMEDIATE')
    clock = [100.0]
    startup = receipt_startup.ReceiptInitializer(clock=lambda: clock[0])
    ready = None
    try:
        started = time.monotonic()
        assert startup.poll(path) is None
        assert time.monotonic() - started < 0.2
        wait_for(lambda: startup.status()['state'] == 'retrying')
        status = startup.status()
        assert status['error_type'] == 'OperationalError'
        assert 'locked' in status['error']
        assert status['retry_in_seconds'] == 2.0
        for _ in range(30):
            assert startup.poll(path) is None
        assert startup.status()['retry_in_seconds'] == 2.0
        blocker.rollback()
        clock[0] += 2.1
        startup.poll(path)
        ready = wait_for(lambda: startup.poll(path))
        assert ready.prior(call, digest)['status'] == 'succeeded'
        assert startup.status()['state'] == 'ready'
        assert startup.status()['error'] is None
    finally:
        blocker.close()
        startup.cancel()
        if ready is not None:
            ready.close()


def test_disable_fences_worker_result_and_reenable_never_overlaps(tmp_path):
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    calls = []
    stale = SimpleNamespace(close=closed.set)
    replacement = SimpleNamespace(close=MagicMock())
    def factory(path):
        assert threading.current_thread() is not threading.main_thread()
        calls.append(path)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
            return stale
        return replacement
    startup = receipt_startup.ReceiptInitializer(factory=factory)
    path = tmp_path / 'receipts.sqlite'
    startup.poll(path)
    assert entered.wait(2)
    started = time.monotonic()
    startup.cancel()
    assert time.monotonic() - started < 0.2
    for _ in range(20):
        assert startup.poll(path) is None
    assert len(calls) == 1
    release.set()
    assert closed.wait(2)
    assert wait_for(lambda: startup.poll(path)) is replacement
    assert len(calls) == 2
    startup.cancel()
    replacement.close()


def test_repeated_failure_is_backed_off_and_logged_once_until_recovery(tmp_path, monkeypatch):
    clock = [0.0]
    attempts = []
    fail = [True]
    ready = SimpleNamespace(close=MagicMock())
    def factory(path):
        attempts.append(path)
        if fail[0]:
            raise sqlite3.OperationalError('read-only database')
        return ready
    warning = MagicMock()
    monkeypatch.setattr(receipt_startup.logger, 'warning', warning)
    startup = receipt_startup.ReceiptInitializer(factory=factory, clock=lambda: clock[0])
    path = tmp_path / 'receipts.sqlite'
    for expected_delay in (2, 4, 8, 16, 32, 60, 60):
        startup.poll(path)
        wait_for(lambda: startup.status()['retry_in_seconds'] == expected_delay)
        assert startup.poll(path) is None
        clock[0] += expected_delay
    assert len(attempts) == 7
    assert warning.call_count == 1
    fail[0] = False
    assert wait_for(lambda: startup.poll(path)) is ready
    assert startup.status()['error'] is None
    startup.cancel()
    fail[0] = True
    startup.poll(path)
    wait_for(lambda: startup.status()['error'])
    assert warning.call_count == 2
    startup.cancel()


def test_failed_constructor_closes_partial_transaction(tmp_path, monkeypatch):
    connect = sqlite3.connect
    connections = []
    class Connection:
        def __init__(self, *args, **kwargs):
            self.real = connect(*args, **kwargs)
            self.closed = False
            connections.append(self)
        def execute(self, statement, *args):
            if statement.startswith('CREATE TABLE IF NOT EXISTS calls'):
                assert self.real.in_transaction
                raise sqlite3.OperationalError('injected schema failure')
            return self.real.execute(statement, *args)
        def close(self):
            self.closed = True
            self.real.close()
    monkeypatch.setattr(receipts.sqlite3, 'connect', Connection)
    path = tmp_path / 'receipts.sqlite'
    with pytest.raises(sqlite3.OperationalError, match='injected schema failure'):
        receipts.Receipts(path)
    assert connections[0].closed
    with connect(path, timeout=0) as probe:
        probe.execute('BEGIN IMMEDIATE')  # No lock leaked by the failed constructor.
        probe.rollback()


def test_service_waits_for_receipts_and_registers_blender_only_on_main_thread(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    ready = SimpleNamespace(close=MagicMock())
    def factory(path):
        assert threading.current_thread() is not threading.main_thread()
        entered.set()
        assert release.wait(5)
        return ready
    initializer = receipt_startup.ReceiptInitializer(factory=factory)
    handlers = SimpleNamespace(undo_pre=[], redo_pre=[], load_pre=[], load_post=[])
    timers = MagicMock()
    def resource(kind):
        assert threading.current_thread() is threading.main_thread()
        return str(tmp_path)
    fake_bpy = SimpleNamespace(context=SimpleNamespace(window_manager=SimpleNamespace(
        mixar_ui_enable=MagicMock())), utils=SimpleNamespace(user_resource=resource),
        app=SimpleNamespace(handlers=handlers, timers=timers))
    monkeypatch.setattr(service, 'bpy', fake_bpy)
    monkeypatch.setattr(service, '_registered', False)
    monkeypatch.setattr(service, '_receipts', None)
    monkeypatch.setattr(service, '_receipt_initializer', initializer)
    monkeypatch.setattr(service, 'invalidate', lambda *args: None)
    assert service.register() is False
    assert entered.wait(2)
    assert not service._registered and service._receipts is None
    assert not handlers.undo_pre and not timers.register.called
    with pytest.raises(UIError, match='starting'):
        service.submit(str(uuid4()), 'mixar_scenes', {}, str(uuid4()))
    release.set()
    wait_for(lambda: initializer.status()['state'] == 'ready')
    timers.register.side_effect = RuntimeError('timer unavailable during startup')
    with pytest.raises(RuntimeError, match='timer unavailable'):
        service.register()
    assert service._receipts is ready and not service._registered
    timers.register.reset_mock(side_effect=True)
    assert wait_for(service.register) is True
    assert service._receipts is ready and service._registered
    assert service.register() is True
    timers.register.assert_called_once()
    service.unregister()
    assert not service._registered and service._receipts is None
    ready.close.assert_called_once()


def test_service_exit_cancels_pending_worker_without_bpy_access(tmp_path, monkeypatch):
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    def factory(path):
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(close=closed.set)
    initializer = receipt_startup.ReceiptInitializer(factory=factory)
    class FreedBlender:
        def __getattr__(self, name):
            raise AssertionError('Receipt shutdown touched freed Blender state')
    monkeypatch.setattr(service, 'bpy', FreedBlender())
    monkeypatch.setattr(service, '_registered', False)
    monkeypatch.setattr(service, '_receipts', None)
    monkeypatch.setattr(service, '_receipt_initializer', initializer)
    monkeypatch.setattr(service.ownership, 'forget', lambda: None)
    initializer.poll(tmp_path / 'receipts.sqlite')
    assert entered.wait(2)
    service.unregister(shutdown=True)
    assert initializer.status()['state'] == 'disabled'
    release.set()
    assert closed.wait(2)
    assert initializer.status()['state'] == 'disabled'
    assert service._receipts is None and not service._registered
