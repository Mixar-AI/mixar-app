# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import datetime, timezone
from pathlib import Path
import threading
import time

from mixar.modules.project_versioning.core.checkpoint_service import CheckpointService
from mixar.modules.project_versioning.core.models import (
    CheckpointRequest,
    CheckpointState,
    ProjectRecord,
    RemoteConflict,
    RemotePushRequest,
    RemoteResultState,
    RemoteSession,
    RemoteTransferOutcome,
)
from mixar.modules.project_versioning.core.sdk_adapter import LoreRemoteConflict


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def ensure_repository(self, project):
        self.calls.append(("ensure", threading.current_thread().name))

    def stage(self, project, paths):
        self.calls.append(("stage", list(paths)))

    def commit(self, project, message):
        self.calls.append(("commit", message))
        return "a" * 64

    def shutdown(self):
        self.calls.append(("shutdown", threading.current_thread().name))

    def push(self, project, session, *, branch):
        self.calls.append(("push", branch, session.token))
        return RemoteTransferOutcome("b" * 64, False)

    def logout(self, repository_path, session):
        self.calls.append(("logout", repository_path, session.user_id))


def _request(tmp_path: Path, request_id: str = "checkpoint-1") -> CheckpointRequest:
    blend = tmp_path / "scene.blend"
    blend.write_bytes(b"BLENDER-v500")
    stat = blend.stat()
    project = ProjectRecord(
        project_id="project",
        repository_id="repository",
        identity_id="identity",
        root_path=str(tmp_path),
        blend_path=str(blend),
        default_branch="main",
    )
    (tmp_path / ".mixar" / "checkpoints").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".mixar" / "project.json").write_text("{}")
    return CheckpointRequest(
        request_id=request_id,
        project=project,
        filepath=str(blend),
        relative_blend_path="scene.blend",
        source="manual",
        message="save",
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        epoch=1,
        captured_at=datetime.now(timezone.utc).isoformat(),
    )


def _await_result(service: CheckpointService, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        results = service.drain_results()
        if results:
            return results[-1]
        time.sleep(0.01)
    raise AssertionError("checkpoint worker did not produce a result")


def test_worker_owns_lore_calls_and_stages_only_allowlisted_paths(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = CheckpointService(adapter_factory=lambda: adapter)
    service.start()
    assert service.submit(_request(tmp_path))

    result = _await_result(service)
    service.shutdown()

    assert result.state == CheckpointState.SUCCEEDED
    assert result.revision == "a" * 64
    assert adapter.calls[0] == ("ensure", "mixar-lore-checkpoints")
    assert adapter.calls[1][0] == "stage"
    assert adapter.calls[1][1][0:2] == ["scene.blend", ".mixar/project.json"]
    assert adapter.calls[1][1][2].startswith(".mixar/checkpoints/")
    assert adapter.calls[-1] == ("shutdown", "mixar-lore-checkpoints")


def test_changed_file_is_superseded_before_lore_work(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    request = _request(tmp_path)
    Path(request.filepath).write_bytes(b"changed after capture")
    service = CheckpointService(adapter_factory=lambda: adapter)
    service.start()
    service.submit(request)

    result = _await_result(service)
    service.shutdown()

    assert result.state == CheckpointState.SUPERSEDED
    assert [call[0] for call in adapter.calls] == ["shutdown"]


def test_checkpoint_worker_modules_do_not_import_bpy() -> None:
    root = Path(__file__).parents[2] / "src/scripts/mixar/modules/project_versioning/core"
    for name in ("checkpoint_service.py", "sdk_adapter.py", "project_store.py"):
        assert "import bpy" not in (root / name).read_text(encoding="utf-8")


def test_remote_push_reports_up_to_date_and_logs_out(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = CheckpointService(adapter_factory=lambda: adapter)
    request = _request(tmp_path)
    remote = RemotePushRequest(
        request_id="push-1",
        project=request.project,
        session=RemoteSession(
            repository_url="lore://example.test/project",
            auth_url="https://auth.example.test",
            token="ephemeral-token",
            resource="project",
            user_id="user",
        ),
        epoch=7,
    )
    service.start()
    assert service.submit_remote(remote)

    result = _await_result(service)
    service.shutdown()

    assert result.state == RemoteResultState.UP_TO_DATE
    assert result.revision == "b" * 64
    assert result.epoch == 7
    assert ("push", "main", "ephemeral-token") in adapter.calls
    assert ("logout", str(tmp_path), "user") in adapter.calls


def test_remote_conflict_is_a_typed_result(tmp_path: Path) -> None:
    class ConflictAdapter(FakeAdapter):
        def push(self, project, session, *, branch):
            from mixar.modules.project_versioning.core.models import RemoteHeads

            heads = RemoteHeads(branch, "a", "b", True, True)
            raise LoreRemoteConflict(RemoteConflict.DIVERGED, heads)

    request = _request(tmp_path)
    service = CheckpointService(adapter_factory=ConflictAdapter)
    service.start()
    service.submit_remote(
        RemotePushRequest(
            request_id="push-conflict",
            project=request.project,
            session=RemoteSession(
                "lore://example.test/project",
                "https://auth.example.test",
                "token",
            ),
        )
    )

    result = _await_result(service)
    service.shutdown()

    assert result.state == RemoteResultState.CONFLICT
    assert result.conflict == RemoteConflict.DIVERGED
    assert result.error is None
