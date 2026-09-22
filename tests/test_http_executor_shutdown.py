# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""HTTP requests must not keep Python alive or deliver after teardown."""
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from mixar.modules.common.api.core.worker_pool import HTTPWorkerPool
from mixar.modules.common.api.executor import AsyncRequest, HTTPExecutor, stop_executor


@pytest.fixture
def executor():
    HTTPExecutor.reset()
    executor = HTTPExecutor()
    executor.start(pool_size=1)
    yield executor
    executor.stop()


def test_stalled_worker_does_not_pin_interpreter_exit():
    source = Path(__file__).resolve().parents[1] / (
        'src/scripts/mixar/modules/common/api/core/worker_pool.py')
    # A subprocess is essential: shutdown(wait=False) alone already passed
    # with ThreadPoolExecutor, but its interpreter-exit hook joined forever.
    script = f"""
import importlib.util
import threading
spec = importlib.util.spec_from_file_location('worker_pool', {str(source)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
pool = module.HTTPWorkerPool(1)
entered = threading.Event()
release = threading.Event()
def stalled():
    entered.set()
    release.wait(60)
pool.submit(stalled)
assert entered.wait(2)
pool.shutdown(wait=False)
"""
    completed = subprocess.run([sys.executable, '-c', script], timeout=5,
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_shutdown_cancels_queued_work_and_rejects_new_work():
    pool = HTTPWorkerPool(1)
    entered, release = threading.Event(), threading.Event()

    def stalled():
        entered.set()
        release.wait(3)

    running = pool.submit(stalled)
    assert entered.wait(2)
    queued = pool.submit(lambda: pytest.fail('Queued request executed after shutdown'))
    try:
        pool.shutdown(wait=False)
        assert queued.cancelled()
        with pytest.raises(RuntimeError):
            pool.submit(lambda: None)
    finally:
        release.set()
        running.result(timeout=2)
        pool.shutdown(wait=True)


def test_explicit_wait_drains_requests():
    pool = HTTPWorkerPool(2)
    futures = [pool.submit(lambda n=n: n * 2) for n in range(10)]
    pool.shutdown(wait=True, cancel_futures=False)
    assert [f.result() for f in futures] == list(range(0, 20, 2))


@pytest.mark.parametrize('failure', [False, True])
def test_waiting_stop_delivers_running_and_queued_completions(executor, monkeypatch, failure):
    entered, release = threading.Event(), threading.Event()
    values = []
    error = ValueError('network failure')
    shutdown = executor._pool.shutdown

    def request():
        entered.set()
        assert release.wait(3)
        if failure:
            raise error
        return 'response'

    def drain(**kwargs):
        # Both requests must complete during stop(), never before it begins.
        release.set()
        shutdown(**kwargs)

    monkeypatch.setattr(executor._pool, 'shutdown', drain)
    try:
        executor.submit(AsyncRequest('running', request), lambda *args: values.append(args))
        assert entered.wait(2)
        executor.submit(AsyncRequest('queued', request), lambda *args: values.append(args))
        stop_executor(wait=True)
        expected = (None, error) if failure else ('response', None)
        assert values == [('running', *expected), ('queued', *expected)]
        assert executor.pending_count() == 0
        assert not executor.is_running
        with pytest.raises(RuntimeError):
            executor.submit(AsyncRequest('late', request), lambda *args: None)
    finally:
        release.set()
        shutdown(wait=True)


def test_waiting_stop_does_not_disable_restarted_executor(executor, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    new_entered, new_release = threading.Event(), threading.Event()
    delivered = threading.Event()
    values = []
    shutdown = executor._pool.shutdown

    def request(entered, release):
        entered.set()
        assert release.wait(3)
        return 'response'

    def complete(*args):
        values.append(('new', args))
        delivered.set()

    def restart(*args):
        values.append(('old', args))
        executor.start()
        executor.submit(AsyncRequest('same-id', lambda: request(new_entered, new_release)),
                        complete)

    def drain(**kwargs):
        release.set()
        shutdown(**kwargs)

    monkeypatch.setattr(executor._pool, 'shutdown', drain)
    try:
        executor.submit(AsyncRequest('same-id', lambda: request(entered, release)), restart)
        assert entered.wait(2)
        executor.stop(wait=True)
        assert values == [('old', ('same-id', 'response', None))]
        assert executor.is_running
        assert new_entered.wait(2)
        assert executor.pending_count() == 1
        new_release.set()
        assert delivered.wait(2)
        assert values == [('old', ('same-id', 'response', None)),
                          ('new', ('same-id', 'response', None))]
        assert executor.pending_count() == 0
    finally:
        release.set()
        new_release.set()
        shutdown(wait=True)


@pytest.mark.parametrize('failure', [False, True])
def test_request_completion_reports_result_or_error(executor, failure):
    delivered = threading.Event()
    values = []

    def request():
        if failure:
            raise ValueError('network failure')
        return 'response'

    def complete(*args):
        values.append(args)
        delivered.set()

    executor.submit(AsyncRequest('test', request), complete)
    assert delivered.wait(2)
    assert executor.pending_count() == 0
    assert values[0][0] == 'test'
    if failure:
        assert values[0][1] is None and isinstance(values[0][2], ValueError)
    else:
        assert values == [('test', 'response', None)]


def test_restart_drops_old_completion_without_losing_new_request(executor):
    old_entered, old_release = threading.Event(), threading.Event()
    new_entered, new_release = threading.Event(), threading.Event()
    delivered = threading.Event()
    values = []

    def request(entered, release):
        entered.set()
        assert release.wait(3)
        return 'response'

    executor.submit(AsyncRequest('same-id', lambda: request(old_entered, old_release)),
                    lambda *args: values.append(('old', args)))
    assert old_entered.wait(2)
    old_pool = executor._pool
    executor.stop()
    executor.start()

    def complete(*args):
        values.append(('new', args))
        delivered.set()

    executor.submit(AsyncRequest('same-id', lambda: request(new_entered, new_release)), complete)
    try:
        assert new_entered.wait(2)
        old_release.set()
        old_pool.shutdown(wait=True)
        assert values == []
        assert executor.pending_count() == 1
        new_release.set()
        assert delivered.wait(2)
        assert values == [('new', ('same-id', 'response', None))]
    finally:
        old_release.set()
        new_release.set()


def test_cancelled_request_is_removed_from_tracking(executor):
    entered, release = threading.Event(), threading.Event()
    pool = executor._pool
    executor.submit(AsyncRequest('running', lambda: (entered.set(), release.wait(3))),
                    lambda *args: None)
    assert entered.wait(2)
    called = []
    executor.submit(AsyncRequest('queued', lambda: called.append('work')),
                    lambda *args: called.append('callback'))
    try:
        assert executor.cancel('queued')
        assert executor.pending_count() == 1
    finally:
        release.set()
        pool.shutdown(wait=True)
    assert called == []
