# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generation results survive actual socket loss, queue clearing and retries."""
import gc
import json
from queue import SimpleQueue
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import weakref

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.job_queue.core import agent_results as AR
from mixar.modules.common.job_queue.core import queue_manager as QM
from mixar.modules.common.job_queue.core.job import Job, JobState
from mixar.modules.space_mixie_chat.core.jsonrpc_client import JSONRPCWebSocketClient
from mixar.modules.space_mixie_chat.core.socket_writer import start_writer


@pytest.fixture
def delivery(monkeypatch):
    socket = JSONRPCWebSocketClient('http://unused', 'test')
    socket._connected = socket._handshake_complete = True
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(AR, '_pending', {}, raising=False)
    monkeypatch.setattr(AR, '_responses', SimpleQueue(), raising=False)
    monkeypatch.setattr(AR, '_arm_retry', Mock(), raising=False)
    monkeypatch.setattr(AR, 'time', SimpleNamespace(monotonic=lambda: clock.now), raising=False)
    monkeypatch.setattr(AR, '_get_client', lambda: socket if socket.is_connected else None)
    monkeypatch.setattr(QM, '_queues', {})
    # Retain actual queue transitions and callback wiring; no unrelated UI.
    for name in ('_notify_failure_toasts', '_refresh_queue_toast', '_ensure_status_pump'):
        monkeypatch.setattr(QM.FeatureQueue, name, lambda self: None)
    monkeypatch.setattr(QM, 'redraw_3d_views', lambda: None)
    return SimpleNamespace(socket=socket, clock=clock)


def job(state=JobState.SUCCESS):
    value = Job(label='Wizard')
    value.agent_ref = {'generation_id': 'gen-qa', 'session_id': 'session', 'run_id': 'run'}
    value.state = state
    value.imported_object_names = 'Wizard, Staff'
    return value


def ack(socket, frame, result=None):
    socket._handle_message({'jsonrpc': '2.0', 'id': frame['id'],
                            'result': result or {'received': True, 'delivered': True}})


def test_queue_acceptance_is_not_an_acknowledgement(delivery):
    value = job()
    assert AR.report_agent_results([value]) == 1
    assert not value._agent_reported
    frame = json.loads(delivery.socket._outbound.get_nowait())
    assert frame['method'] == 'generation.agent_result' and frame['id']
    assert AR.report_agent_results([value]) == 0  # one in-flight attempt
    worker = threading.Thread(target=ack, args=(delivery.socket, frame))
    worker.start()
    worker.join()
    assert not value._agent_reported  # reader only enqueues an acknowledgement
    assert AR._retry_pending() is None
    assert value._agent_reported and not AR._pending
    assert AR.report_agent_results([value]) == 0


def test_real_disconnect_drain_retries_the_same_outcome(delivery, monkeypatch):
    value = job()
    assert AR.report_agent_results([value]) == 1
    socket = delivery.socket
    socket._running.set()

    def disconnect():
        socket._running.clear()
        return False

    monkeypatch.setattr(socket, '_do_connect', disconnect)
    socket._run_loop()  # actual callback failure and outbound-discard path
    assert socket._outbound.empty()
    assert not socket._pending_callbacks and not value._agent_reported
    AR._retry_pending()
    socket._connected = socket._handshake_complete = True
    delivery.clock.now += AR._RETRY_INTERVAL
    assert AR.report_all_agent_results() == 1
    frame = json.loads(socket._outbound.get_nowait())
    assert frame['params']['generation_id'] == 'gen-qa'
    assert frame['params']['result_names'] == ['Wizard', 'Staff']
    ack(socket, frame)
    assert AR._retry_pending() is None
    assert value._agent_reported


def test_writer_send_failure_leaves_result_retryable(delivery):
    socket = delivery.socket
    value = job()
    AR.report_agent_results([value])
    closed = threading.Event()

    def fail(frame):
        raise OSError('broken socket')

    socket._ws = SimpleNamespace(send=fail, close=closed.set)
    socket._running.set()
    stopped, writer = start_writer(socket)
    try:
        assert closed.wait(2)
        writer.join(2)
        assert not value._agent_reported
        # Even if the old writer cannot expire the RPC, the outbox deadline
        # makes progress once a connection is available again.
        socket._connected = True
        delivery.clock.now += AR._REQUEST_TIMEOUT
        assert AR.report_all_agent_results() == 1
    finally:
        stopped.set()
        socket._running.clear()
        writer.join(2)


@pytest.mark.parametrize('result', [
    {'code': -32020, 'message': 'timeout'},
    {'received': False, 'reason': 'relay_failed'},
    {'received': True, 'delivered': False, 'reason': 'relay_failed'},
])
def test_missing_or_failed_acknowledgement_retries_without_queue_activity(delivery, result):
    value = job()
    AR.report_agent_results([value])
    frame = json.loads(delivery.socket._outbound.get_nowait())
    ack(delivery.socket, frame, result)
    assert AR._retry_pending() == AR._RETRY_INTERVAL
    assert not value._agent_reported
    delivery.clock.now += AR._RETRY_INTERVAL
    AR._retry_pending()
    retry = json.loads(delivery.socket._outbound.get_nowait())
    assert retry['id'] != frame['id'] and retry['params'] == frame['params']
    ack(delivery.socket, retry)
    assert AR._retry_pending() is None
    assert value._agent_reported


@pytest.mark.parametrize('result', [
    {'received': True, 'relayed': True, 'delivered': False},
    {'received': True, 'delivered': False, 'reason': 'unknown_generation'},
])
def test_backend_relay_or_closed_run_acknowledgement_retires_result(delivery, result):
    value = job()
    AR.report_agent_results([value])
    ack(delivery.socket, json.loads(delivery.socket._outbound.get_nowait()), result)
    assert AR._retry_pending() is None
    assert value._agent_reported


@pytest.mark.parametrize('clear,state,status', [
    ('clear_completed', JobState.SUCCESS, 'succeeded'),
    ('clear_completed', JobState.FAILED, 'failed'),
    ('clear_all', JobState.RUNNING_DOWNLOAD, 'cancelled'),
    ('clear_all', JobState.SUCCESS, 'succeeded'),
])
def test_cleared_job_outlives_its_queue_only_as_callback_params(delivery, clear, state, status):
    delivery.socket._connected = False
    queue = QM.get_queue('qa')
    value = job(state)
    job_ref = weakref.ref(value)
    queue._jobs.append(value)
    getattr(queue, clear)()
    assert queue.snapshot() == []
    assert not value._agent_reported
    del value
    gc.collect()
    assert job_ref() is None  # no retained payloads/datablocks via the Job
    delivery.socket._connected = True
    assert AR.report_all_agent_results() == 1
    frame = json.loads(delivery.socket._outbound.get_nowait())
    assert frame['params']['status'] == status
    ack(delivery.socket, frame)
    assert AR._retry_pending() is None


def test_retry_timer_survives_file_load(monkeypatch):
    import bpy
    monkeypatch.setattr(AR, '_pending', {'pending': object()})
    monkeypatch.setattr(bpy.app.timers, 'is_registered', Mock(return_value=False))
    register = Mock()
    monkeypatch.setattr(bpy.app.timers, 'register', register)
    AR._arm_retry()
    register.assert_called_once_with(AR._retry_pending, first_interval=AR._RETRY_INTERVAL, persistent=True)


@pytest.mark.parametrize('result', [
    {'code': -32601, 'message': 'Method not found'},
    {'received': False, 'reason': 'not_owner'},
    {'received': False, 'reason': 'no_agent_ref'},
    {'received': False, 'reason': 'invalid_status'},
])
def test_permanent_rejection_is_retired_without_false_ack_or_reinsertion(delivery, result):
    value = job()
    AR.report_agent_results([value])
    ack(delivery.socket, json.loads(delivery.socket._outbound.get_nowait()), result)
    assert AR._retry_pending() is None
    assert not value._agent_reported
    assert AR.report_agent_results([value]) == 0
    assert not AR._pending


@pytest.mark.parametrize('response', [None, {'unexpected': 'response'}, {'code': -32020},
                                      {'received': False, 'reason': []}])
def test_retry_budget_stops_missing_or_malformed_responses(delivery, monkeypatch, response):
    monkeypatch.setattr(AR, '_MAX_ATTEMPTS', 3, raising=False)
    value = job()
    for _ in range(3):
        assert AR.report_agent_results([value]) == 1
        frame = json.loads(delivery.socket._outbound.get_nowait())
        if response is not None:
            ack(delivery.socket, frame, response)
            AR._retry_pending()
        delivery.clock.now += AR._REQUEST_TIMEOUT + AR._RETRY_INTERVAL
    assert AR._retry_pending() is None
    assert not value._agent_reported
    assert AR.report_agent_results([value]) == 0
    assert delivery.socket._outbound.empty()
    # A very late acknowledgement must not resurrect the retired entry.
    ack(delivery.socket, frame)
    assert AR._retry_pending() is None and not value._agent_reported


def test_offline_outcome_expires_even_without_a_connection(delivery, monkeypatch):
    monkeypatch.setattr(AR, '_MAX_AGE', 60, raising=False)
    value = job()
    delivery.socket._connected = False
    assert AR.report_agent_results([value]) == 0 and AR._pending
    delivery.clock.now += 60
    assert AR._retry_pending() is None
    delivery.socket._connected = True
    assert AR.report_agent_results([value]) == 0
    assert not value._agent_reported and not AR._pending


def test_final_attempt_can_still_be_acknowledged(delivery, monkeypatch):
    monkeypatch.setattr(AR, '_MAX_ATTEMPTS', 1)
    value = job()
    AR.report_agent_results([value])
    frame = json.loads(delivery.socket._outbound.get_nowait())
    assert AR._retry_pending() == AR._RETRY_INTERVAL
    ack(delivery.socket, frame)
    assert AR._retry_pending() is None and value._agent_reported


def test_send_exceptions_exhaust_budget_and_log_once(delivery, monkeypatch):
    monkeypatch.setattr(AR, '_MAX_ATTEMPTS', 2)
    logger = Mock()
    monkeypatch.setattr(AR, 'logger', logger)
    monkeypatch.setattr(delivery.socket, 'send_request', Mock(side_effect=OSError('offline')))
    value = job()
    for _ in range(3):
        AR.report_agent_results([value])
        delivery.clock.now += AR._RETRY_INTERVAL
    assert not AR._pending and not value._agent_reported
    AR.report_agent_results([value])
    assert delivery.socket.send_request.call_count == 2
    assert sum('giving up' in str(call) for call in logger.warning.call_args_list) == 1
