# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Idle delivery wakeups, teardown fences and the timer-removal race."""

import threading
from types import SimpleNamespace

import pytest
from _open_run_support import clean_state, live_bpy
from mixar.modules.space_mixie_chat.core import main_thread_executor, turn_events
from mixar.modules.space_mixie_chat.core.turn_event_pump import TurnEventPump


@pytest.fixture
def host(monkeypatch, live_bpy):
    deferred, registered = [], {}
    def register(fn, **options):
        assert threading.current_thread() is threading.main_thread()
        assert fn not in registered  # Mirrors Blender's duplicate timer rejection.
        registered[fn] = options
    monkeypatch.setattr(main_thread_executor, 'run_on_main_thread',
                        lambda fn: deferred.append(fn) or True)
    monkeypatch.setattr(live_bpy.app, 'timers', SimpleNamespace(
        register=register, is_registered=lambda fn: fn in registered,
        unregister=lambda fn: registered.pop(fn)))
    def start():
        while deferred:
            deferred.pop(0)()
    return SimpleNamespace(deferred=deferred, timers=registered, start=start)


def test_connection_stays_idle_and_worker_wakes_delivery_immediately(host, monkeypatch):
    delivered = []
    monkeypatch.setattr(turn_events, '_consume', lambda method, params: delivered.append(params))
    turn_events.arm()
    assert not host.deferred and not host.timers
    worker = threading.Thread(target=lambda: turn_events.handle_turn_notification(
        'agent.command.result', {'session_id': 's', 'command_id': 'c'}))
    worker.start()
    worker.join()
    assert not delivered and not host.timers
    assert len(host.deferred) == 1
    host.start()
    tick = next(iter(host.timers))
    assert host.timers[tick]['first_interval'] == 0.0
    assert tick() is None
    assert delivered == [{'session_id': 's', 'command_id': 'c'}]
    assert not turn_events._pump.pending()


def test_burst_coalesces_and_backlog_retains_fast_cadence(host, monkeypatch):
    delivered = []
    monkeypatch.setattr(turn_events, '_consume', lambda method, params: delivered.append(params))
    monkeypatch.setattr(turn_events.time, 'monotonic', lambda: 0.0)
    turn_events.arm()
    for n in range(100):
        turn_events.handle_turn_notification('agent.command.result', {'session_id': 's', 'n': n})
    assert len(host.deferred) == 1
    host.start()
    tick = next(iter(host.timers))
    assert tick() == 0.02 and len(delivered) == 64
    assert tick() is None and len(delivered) == 100


def test_arrival_during_final_drain_keeps_consumer_alive(host):
    def drain():
        pump.request()  # Arrives after the drain's empty check.
        return None
    pump = TurnEventPump(drain)
    pump.enable()
    pump.request()
    host.start()
    assert next(iter(host.timers))() == 0.02
    assert pump.pending() and not host.deferred


def test_new_arrival_before_old_timer_removal_gets_fresh_identity(host):
    pump = TurnEventPump(lambda: None)
    pump.enable()
    pump.request()
    host.start()
    old_tick = next(iter(host.timers))
    assert old_tick() is None
    # Blender has not yet removed old_tick from its registry.
    pump.request()
    host.start()
    assert len(host.timers) == 2
    assert pump.pending()
    assert old_tick() is None  # An obsolete callback cannot disarm its successor.
    assert pump.pending()


def test_teardown_fences_deferred_start_and_late_producers(host):
    pump = TurnEventPump(lambda: None)
    pump.enable()
    pump.request()
    pump.stop()
    pump.request()
    host.start()
    assert not host.timers and not pump.pending()
    pump.enable()
    pump.request()
    host.start()
    assert len(host.timers) == 1


def test_file_load_rearms_a_start_dropped_before_consumer_registration(host, monkeypatch):
    delivered = []
    monkeypatch.setattr(turn_events, '_consume', lambda method, params: delivered.append(params))
    turn_events.arm()
    turn_events.handle_turn_notification('agent.command.result', {'session_id': 's'})
    host.deferred.clear()  # File load removes nonpersistent scheduler callbacks.
    assert turn_events._pump.pending() and not host.timers
    turn_events.arm()  # The actual load_post path.
    host.start()
    assert next(iter(host.timers))() is None
    assert delivered == [{'session_id': 's'}]


def test_scheduler_rejection_releases_latch_for_retry(host, monkeypatch):
    pump = TurnEventPump(lambda: None)
    pump.enable()
    monkeypatch.setattr(main_thread_executor, 'run_on_main_thread', lambda fn: False)
    pump.request()
    assert not pump.pending()
    monkeypatch.setattr(main_thread_executor, 'run_on_main_thread',
                        lambda fn: host.deferred.append(fn) or True)
    pump.request()
    host.start()
    assert len(host.timers) == 1


def test_consumer_error_retries_backlog_with_bounded_backoff(host):
    failures = [8]
    delivered = []
    def drain():
        if failures[0]:
            failures[0] -= 1
            raise RuntimeError('test drain failure')
        delivered.append('backlog')
        return None
    pump = TurnEventPump(drain)
    pump.enable()
    pump.request()
    host.start()
    tick = next(iter(host.timers))
    assert [tick() for _ in range(8)] == [0.1, 0.2, 0.4, 0.8, 1.6, 2.0, 2.0, 2.0]
    assert pump.pending()
    assert tick() is None and delivered == ['backlog']
    assert not pump.pending()


def test_overflow_recovery_failure_stays_pending_until_success(host, monkeypatch):
    attempts = []
    def recover(*, session_ids):
        attempts.append(session_ids)
        if len(attempts) == 1:
            raise RuntimeError('temporary recovery failure')
    monkeypatch.setattr(turn_events, 'reconnect', recover)
    monkeypatch.setattr(turn_events, '_MAX_BYTES', 0)
    turn_events.arm()
    turn_events.handle_turn_notification('agent.turn.event', {'session_id': 's'})
    host.start()
    tick = next(iter(host.timers))
    assert tick() == 0.1
    assert turn_events._overflow == {'s'}
    assert tick() is None
    assert attempts == [['s'], ['s']]
    assert not turn_events._overflow and not turn_events._pump.pending()
