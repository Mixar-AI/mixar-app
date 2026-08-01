# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Single-owner Lore worker with coalescing and stale-file protection."""

from __future__ import annotations

from collections import OrderedDict, deque
import os
from queue import Empty, Queue
import threading
from typing import Callable

from .checkpoint_manifest import write_checkpoint_manifest
from .models import (
    CheckpointRequest,
    CheckpointResult,
    CheckpointState,
    RemoteCloneRequest,
    RemoteCreateRequest,
    RemoteOperation,
    RemoteOperationResult,
    RemotePushRequest,
    RemoteRequest,
    RemoteResultState,
    RemoteSyncRequest,
)
from .sdk_adapter import LoreRemoteConflict, LoreSdkAdapter


class CheckpointService:
    def __init__(self, adapter_factory: Callable[[], object] = LoreSdkAdapter):
        self._adapter_factory = adapter_factory
        self._condition = threading.Condition()
        self._pending: OrderedDict[str, CheckpointRequest] = OrderedDict()
        self._remote_pending: deque[RemoteRequest] = deque()
        self._results: Queue[CheckpointResult | RemoteOperationResult] = Queue()
        self._thread: threading.Thread | None = None
        self._accepting = False

    def start(self) -> None:
        with self._condition:
            if self._thread and self._thread.is_alive():
                return
            self._accepting = True
            self._thread = threading.Thread(
                target=self._run, name="mixar-lore-checkpoints", daemon=True
            )
            self._thread.start()

    def submit(self, request: CheckpointRequest) -> bool:
        with self._condition:
            if not self._accepting:
                return False
            key = request.project.root_path
            replaced = self._pending.pop(key, None)
            if replaced is not None:
                self._results.put(
                    CheckpointResult(
                        request_id=replaced.request_id,
                        filepath=replaced.filepath,
                        epoch=replaced.epoch,
                        state=CheckpointState.SUPERSEDED,
                    )
                )
            self._pending[key] = request
            self._condition.notify()
            return True

    def submit_remote(self, request: RemoteRequest) -> bool:
        """Queue an interactive remote operation without exposing its session."""
        with self._condition:
            if not self._accepting:
                return False
            self._remote_pending.append(request)
            self._condition.notify()
            return True

    def drain_results(self) -> list[CheckpointResult | RemoteOperationResult]:
        results = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except Empty:
                return results

    @staticmethod
    def _unchanged(request: CheckpointRequest) -> bool:
        try:
            stat = os.stat(request.filepath)
            return stat.st_size == request.size and stat.st_mtime_ns == request.mtime_ns
        except OSError:
            return False

    def _run(self) -> None:
        adapter = self._adapter_factory()
        try:
            while True:
                with self._condition:
                    while self._accepting and not self._pending and not self._remote_pending:
                        self._condition.wait()
                    if not self._accepting and not self._pending and not self._remote_pending:
                        return
                    if self._remote_pending:
                        request = self._remote_pending.popleft()
                    else:
                        _, request = self._pending.popitem(last=False)
                if isinstance(request, CheckpointRequest):
                    self._process(adapter, request)
                else:
                    self._process_remote(adapter, request)
        finally:
            try:
                adapter.shutdown()
            except Exception:
                pass

    def _process(self, adapter, request: CheckpointRequest) -> None:
        try:
            if not self._unchanged(request):
                state = CheckpointState.SUPERSEDED
                self._results.put(
                    CheckpointResult(request.request_id, request.filepath, request.epoch, state)
                )
                return
            adapter.ensure_repository(request.project)
            manifest = write_checkpoint_manifest(request)
            paths = [request.relative_blend_path, ".mixar/project.json", manifest]
            adapter.stage(request.project, paths)
            if not self._unchanged(request):
                self._results.put(
                    CheckpointResult(
                        request.request_id,
                        request.filepath,
                        request.epoch,
                        CheckpointState.SUPERSEDED,
                    )
                )
                return
            revision = adapter.commit(request.project, request.message)
            self._results.put(
                CheckpointResult(
                    request.request_id,
                    request.filepath,
                    request.epoch,
                    CheckpointState.SUCCEEDED,
                    revision=revision,
                )
            )
        except Exception as exc:  # SDK/native failures stay inside the pilot
            self._results.put(
                CheckpointResult(
                    request.request_id,
                    request.filepath,
                    request.epoch,
                    CheckpointState.FAILED,
                    error=str(exc),
                )
            )

    @staticmethod
    def _remote_operation(request: RemoteRequest) -> RemoteOperation:
        if isinstance(request, RemoteCreateRequest):
            return RemoteOperation.CREATE
        if isinstance(request, RemoteCloneRequest):
            return RemoteOperation.CLONE
        if isinstance(request, RemotePushRequest):
            return RemoteOperation.PUSH
        return RemoteOperation.SYNC

    def _process_remote(self, adapter, request: RemoteRequest) -> None:
        operation = self._remote_operation(request)
        repository_path = (
            request.repository_path
            if isinstance(request, RemoteCloneRequest)
            else request.project.root_path
        )
        try:
            revision = None
            changed = True
            if isinstance(request, RemoteCreateRequest):
                adapter.create_remote_repository(request.project, request.session)
            elif isinstance(request, RemoteCloneRequest):
                adapter.clone_remote(
                    request.repository_path,
                    request.session,
                    revision=request.revision,
                )
            elif isinstance(request, RemotePushRequest):
                outcome = adapter.push(
                    request.project,
                    request.session,
                    branch=request.branch or request.project.default_branch,
                )
                revision, changed = outcome.revision, outcome.changed
            elif isinstance(request, RemoteSyncRequest):
                outcome = adapter.sync(
                    request.project,
                    request.session,
                    branch=request.branch or request.project.default_branch,
                )
                revision, changed = outcome.revision, outcome.changed
            self._results.put(
                RemoteOperationResult(
                    request_id=request.request_id,
                    operation=operation,
                    state=(
                        RemoteResultState.SUCCEEDED
                        if changed
                        else RemoteResultState.UP_TO_DATE
                    ),
                    epoch=request.epoch,
                    revision=revision,
                )
            )
        except LoreRemoteConflict as exc:
            self._results.put(
                RemoteOperationResult(
                    request_id=request.request_id,
                    operation=operation,
                    state=RemoteResultState.CONFLICT,
                    epoch=request.epoch,
                    conflict=exc.reason,
                )
            )
        except Exception as exc:
            self._results.put(
                RemoteOperationResult(
                    request_id=request.request_id,
                    operation=operation,
                    state=RemoteResultState.FAILED,
                    epoch=request.epoch,
                    error=str(exc),
                )
            )
        finally:
            adapter.logout(repository_path, request.session)

    def shutdown(self, timeout: float = 3.0) -> None:
        with self._condition:
            self._accepting = False
            self._pending.clear()
            self._remote_pending.clear()
            self._condition.notify_all()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
