# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Daemon HTTP workers with explicit teardown, never interpreter-exit joins.

ThreadPoolExecutor joins even after shutdown(wait=False), before atexit runs.
Network calls cannot be forcibly cancelled, so these workers must never touch
bpy. Their owner discards completions on non-waiting shutdown, or delivers
them while an explicitly waiting shutdown drains the queue.
"""
from concurrent.futures import Future
from queue import Empty, Queue
import threading


def _work(queue):
    while True:
        item = queue.get()
        if item is None:
            return
        future, fn = item
        if future.set_running_or_notify_cancel():
            try:
                result = fn()
            except BaseException as exc:
                future.set_exception(exc)
            else:
                future.set_result(result)
                del result
        # Idle threads must not retain requests, callbacks or response payloads.
        del item, future, fn


class HTTPWorkerPool:
    def __init__(self, max_workers):
        if max_workers < 1:
            raise ValueError('max_workers must be positive')
        self._max_workers = max_workers
        self._queue = Queue()
        self._lock = threading.Lock()
        self._threads = []
        self._stopped = False

    def submit(self, fn):
        with self._lock:
            if self._stopped:
                raise RuntimeError('HTTP worker pool is stopped')
            if len(self._threads) < self._max_workers:
                thread = threading.Thread(
                    target=_work, args=(self._queue,), daemon=True,
                    name=f'MixarAPI_{len(self._threads)}',
                )
                thread.start()
                self._threads.append(thread)
            future = Future()
            self._queue.put((future, fn))
            return future

    def shutdown(self, wait=False, cancel_futures=True):
        cancelled = []
        with self._lock:
            if not self._stopped:
                self._stopped = True
                if cancel_futures:
                    while True:
                        try:
                            future, _fn = self._queue.get_nowait()
                        except Empty:
                            break
                        cancelled.append(future)
                for _thread in self._threads:
                    self._queue.put(None)
        # Future callbacks can re-enter the pool; never invoke under its lock.
        for future in cancelled:
            future.cancel()
        if wait:
            for thread in self._threads:
                thread.join()
