# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end tests for the local Add-on Project Mode transaction boundary."""

import json
from queue import Empty
import stat
import sys
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.addon_project.constants import (
    CAPABILITY,
    PROTOCOL_VERSION,
    RPC_DESCRIBE,
    RPC_METHODS,
    RPC_READ,
    RPC_SEARCH,
    RPC_STAGE_PATCH,
)
from mixar.modules.addon_project.errors import AddonProjectError
from mixar.modules.addon_project.paths import resolve_project_path
from mixar.modules.addon_project.service import AddonProjectService
from mixar.modules.addon_project.checks import run_blender_reload
from mixar.modules.addon_project.transactions import TransactionStore
from mixar.modules.space_mixie_chat.core.jsonrpc_client import JSONRPCWebSocketClient
from mixar.modules.space_mixie_chat.core import sse_handler as sse_module


@pytest.fixture
def linked_project(tmp_path):
    project = tmp_path / "sample_addon"
    project.mkdir()
    (project / "__init__.py").write_text(
        "bl_info = {'name': 'Sample', 'blender': (4, 3, 0), 'category': 'Test'}\n"
        "def register():\n    pass\n\n"
        "def unregister():\n    pass\n",
        encoding="utf-8",
    )
    (project / "operators.py").write_text("def answer():\n    return 41\n", encoding="utf-8")
    service = AddonProjectService(tmp_path / "client_state")
    description = service.link(str(project))
    return service, project, description


def test_protocol_v1_surface_is_stable():
    assert CAPABILITY == "addon_project_v1"
    assert PROTOCOL_VERSION == 1
    assert RPC_METHODS == {
        "addon_project.describe",
        "addon_project.search",
        "addon_project.read",
        "addon_project.stage_patch",
        "addon_project.commit_patch",
        "addon_project.run_checks",
        "addon_project.rollback",
        "addon_project.history",
    }


def _wire(service, description, **extra):
    lease = service.issue_lease(description["project_id"])
    return {
        "protocol_version": PROTOCOL_VERSION,
        "project_id": description["project_id"],
        "lease_id": lease["lease_id"],
        **extra,
    }


def test_link_creates_path_free_manifest_and_description(linked_project):
    _service, project, description = linked_project
    manifest = json.loads((project / ".mixar" / "addon-project.json").read_text(encoding="utf-8"))
    assert manifest["project_id"] == description["project_id"]
    assert manifest["entrypoint"] == "sample_addon"
    assert str(project) not in json.dumps(manifest)
    assert str(project) not in json.dumps(description)
    assert {item["path"] for item in description["files"]} == {"__init__.py", "operators.py"}


def test_project_rpc_requires_matching_ephemeral_lease(linked_project):
    service, _project, description = linked_project
    denied = service.dispatch(RPC_DESCRIBE, {
        "protocol_version": PROTOCOL_VERSION,
        "project_id": description["project_id"],
        "lease_id": "wrong",
    })
    assert denied["success"] is False
    assert denied["error"]["code"] == "project_lease_invalid"

    allowed = service.dispatch(RPC_DESCRIBE, _wire(service, description))
    assert allowed["success"] is True
    assert allowed["revision"] == description["revision"]


def test_read_and_search_use_only_relative_paths(linked_project):
    service, project, description = linked_project
    result = service.dispatch(RPC_READ, _wire(
        service,
        description,
        files=[{"path": "operators.py", "start_line": 1, "end_line": 2}],
    ))
    assert result["success"] is True
    assert result["files"][0]["path"] == "operators.py"
    assert "return 41" in result["files"][0]["content"]
    assert str(project) not in json.dumps(result)
    searched = service.dispatch(RPC_SEARCH, _wire(
        service, description, query="return 41", path_glob="*.py",
    ))
    assert searched["results"] == [{
        "path": "operators.py",
        "line": 2,
        "text": "    return 41",
    }]
    assert str(project) not in json.dumps(searched)


def test_stage_commit_checks_and_conflict_safe_rollback(linked_project):
    service, project, description = linked_project
    operator_record = next(item for item in description["files"] if item["path"] == "operators.py")
    staged = service.stage_patch(description["project_id"], {
        "expected_revision": description["revision"],
        "changes": [{
            "path": "operators.py",
            "operation": "write",
            "expected_sha256": operator_record["sha256"],
            "content": "def answer():\n    return 42\n",
        }, {
            "path": "panels.py",
            "operation": "write",
            "expected_sha256": None,
            "content": "class SAMPLE_PT_panel:\n    pass\n",
        }],
    })
    assert staged["success"] is True
    assert "return 42" in staged["changes"][0]["diff"]
    assert (project / "operators.py").read_text(encoding="utf-8").endswith("return 41\n")

    committed = service.commit_patch(description["project_id"], staged["proposal_id"])
    assert committed["success"] is True
    assert committed["checks"]["success"] is True
    assert (project / "operators.py").read_text(encoding="utf-8").endswith("return 42\n")
    assert (project / "panels.py").is_file()

    rolled_back = service.rollback(
        description["project_id"],
        committed["transaction_id"],
        committed["revision"],
    )
    assert rolled_back["success"] is True
    assert (project / "operators.py").read_text(encoding="utf-8").endswith("return 41\n")
    assert not (project / "panels.py").exists()


def test_commit_refuses_project_drift_without_writing(linked_project):
    service, project, description = linked_project
    record = next(item for item in description["files"] if item["path"] == "operators.py")
    staged = service.stage_patch(description["project_id"], {
        "expected_revision": description["revision"],
        "changes": [{
            "path": "operators.py",
            "expected_sha256": record["sha256"],
            "content": "def answer():\n    return 42\n",
        }],
    })
    (project / "operators.py").write_text("def answer():\n    return 99\n", encoding="utf-8")
    with pytest.raises(AddonProjectError, match="changed after staging"):
        service.commit_patch(description["project_id"], staged["proposal_id"])
    assert "return 99" in (project / "operators.py").read_text(encoding="utf-8")


def test_mid_commit_io_failure_restores_every_written_file(linked_project, monkeypatch):
    service, project, description = linked_project
    record = next(item for item in description["files"] if item["path"] == "operators.py")
    staged = service.stage_patch(description["project_id"], {
        "expected_revision": description["revision"],
        "changes": [{
            "path": "operators.py",
            "expected_sha256": record["sha256"],
            "content": "def answer():\n    return 42\n",
        }, {
            "path": "panels.py",
            "expected_sha256": None,
            "content": "class Panel:\n    pass\n",
        }],
    })
    real_write = TransactionStore._atomic_write

    def fail_second(path, content):
        if path.name == "panels.py":
            raise OSError("simulated full disk")
        return real_write(path, content)

    monkeypatch.setattr(service.transactions, "_atomic_write", fail_second)
    with pytest.raises(OSError, match="full disk"):
        service.commit_patch(description["project_id"], staged["proposal_id"])
    assert (project / "operators.py").read_text(encoding="utf-8").endswith("return 41\n")
    assert not (project / "panels.py").exists()


def test_stage_rejects_invalid_python_before_touching_disk(linked_project):
    service, project, description = linked_project
    record = next(item for item in description["files"] if item["path"] == "operators.py")
    with pytest.raises(AddonProjectError) as error:
        service.stage_patch(description["project_id"], {
            "expected_revision": description["revision"],
            "changes": [{
                "path": "operators.py",
                "expected_sha256": record["sha256"],
                "content": "def broken(:\n",
            }],
        })
    assert error.value.code == "syntax_error"
    assert "return 41" in (project / "operators.py").read_text(encoding="utf-8")


def test_path_traversal_and_outside_symlink_are_rejected(linked_project, tmp_path):
    _service, project, _description = linked_project
    with pytest.raises(AddonProjectError):
        resolve_project_path(project, "../secret.py")
    outside = tmp_path / "secret.py"
    outside.write_text("secret = True\n", encoding="utf-8")
    link = project / "linked.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(AddonProjectError) as error:
        resolve_project_path(project, "linked.py")
    assert error.value.code == "path_escape"


def test_dispatch_scrubs_local_root_from_failures(linked_project):
    service, project, description = linked_project
    result = service.dispatch(RPC_STAGE_PATCH, _wire(
        service,
        description,
        expected_revision=description["revision"],
        changes=[{
            "path": "missing.py",
            "expected_sha256": "wrong",
            "content": f"ROOT = {str(project)!r}\n",
        }],
    ))
    assert result["success"] is False
    assert str(project) not in json.dumps(result)


def test_dispatch_hides_unexpected_local_exception_details(
    linked_project, monkeypatch
):
    service, _project, description = linked_project
    monkeypatch.setattr(
        service,
        "search",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("permission denied: /Users/alice/private/client-state.json")
        ),
    )
    result = service.dispatch(RPC_SEARCH, _wire(
        service,
        description,
        query="needle",
    ))
    assert result["error"] == {
        "code": "internal_error",
        "message": "The local add-on project operation failed",
    }
    assert "/Users/alice" not in json.dumps(result)


def test_jsonrpc_routes_project_requests_and_returns_result():
    calls = []

    def handler(method, params, request_id):
        calls.append((method, params, request_id))
        return {"success": True, "revision": "a" * 64}

    client = JSONRPCWebSocketClient(
        host="http://localhost",
        connection_id="instance-1",
        on_addon_project_request=handler,
    )
    client._handle_message({
        "jsonrpc": "2.0",
        "id": "project-1",
        "method": "addon_project.describe",
        "params": {"project_id": "opaque"},
    })
    assert calls == [("addon_project.describe", {"project_id": "opaque"}, "project-1")]
    response = json.loads(client._outbound.get_nowait())
    assert response["id"] == "project-1"
    assert response["result"]["success"] is True
    with pytest.raises(Empty):
        client._outbound.get_nowait()


def test_jsonrpc_hides_project_handler_exception_details():
    def handler(*_args):
        raise OSError("permission denied: /Users/alice/private/project")

    client = JSONRPCWebSocketClient(
        host="http://localhost",
        connection_id="instance-1",
        on_addon_project_request=handler,
    )
    client._handle_message({
        "jsonrpc": "2.0",
        "id": "project-error",
        "method": "addon_project.describe",
        "params": {"project_id": "opaque"},
    })
    response = json.loads(client._outbound.get_nowait())
    assert response["result"]["error"] == {
        "code": "handler_error",
        "message": "The local add-on project handler failed",
    }
    assert "/Users/alice" not in json.dumps(response)


def test_handshake_advertises_project_capability():
    class FakeSocket:
        def __init__(self):
            self.sent = []

        def send(self, payload):
            self.sent.append(json.loads(payload))

        def settimeout(self, _timeout):
            pass

        def recv(self):
            return json.dumps({"jsonrpc": "2.0", "result": {"success": True}})

    client = JSONRPCWebSocketClient("http://localhost", "instance-1")
    client._ws = FakeSocket()
    assert client._perform_handshake() is True
    assert "addon_project_v1" in client._ws.sent[0]["params"]["capabilities"]


def test_sse_chat_payload_carries_only_path_free_project_context(monkeypatch):
    requests = []

    class Response:
        status_code = 200
        text = ""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_lines(self):
            yield "data: [DONE]"

    class Client:
        def __init__(self, timeout=None):
            pass

        def stream(self, method, url, json=None, headers=None):
            requests.append(json)
            return Response()

        def close(self):
            pass

    class FakeHttpx:
        Timeout = lambda **_kwargs: object()

        class ConnectError(Exception):
            pass

        class TimeoutException(Exception):
            pass

    FakeHttpx.Client = Client

    monkeypatch.setattr(sse_module, "httpx", FakeHttpx)
    context = {
        "mode": "addon_project",
        "protocol_version": 1,
        "project_id": "project-id",
        "lease_id": "lease-id",
        "revision": "a" * 64,
    }
    handler = sse_module.SSEStreamHandler(
        host="http://localhost",
        on_event=lambda _event: None,
        on_error=lambda error: pytest.fail(error),
        on_complete=lambda: None,
    )
    handler._running.set()
    handler._stream_loop(
        "change it", "instance-1", "session-1", False, True, True, None,
        project_context=context,
    )
    assert requests[0]["project_context"] == context
    assert "root" not in requests[0]["project_context"]


def test_blender_reload_exercises_disabled_addon_without_enabling_it(tmp_path, monkeypatch):
    module_name = "reload_check_sample"
    project = tmp_path / "repository"
    package = project / module_name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "events = []\n"
        "def register():\n    events.append('register')\n"
        "def unregister():\n    events.append('unregister')\n",
        encoding="utf-8",
    )

    class AddonUtils:
        @staticmethod
        def disable(*_args, **_kwargs):
            pytest.fail("A disabled add-on must not be disabled again")

        @staticmethod
        def enable(*_args, **_kwargs):
            pytest.fail("A disabled add-on must not be left enabled")

    monkeypatch.setitem(sys.modules, "addon_utils", AddonUtils)
    result = run_blender_reload(project, module_name)
    assert result["success"] is True
    assert result["left_enabled"] is False
    module = sys.modules[module_name]
    assert module.events == ["register", "unregister"]


def test_link_prefers_the_only_blender_addon_package(tmp_path):
    project = tmp_path / "studio_repository"
    helper = project / "shared_helpers"
    addon = project / "designer_addon"
    helper.mkdir(parents=True)
    addon.mkdir()
    (helper / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (addon / "__init__.py").write_text(
        "bl_info = {'name': 'Designer'}\n"
        "def register():\n    pass\n"
        "def unregister():\n    pass\n",
        encoding="utf-8",
    )
    service = AddonProjectService(tmp_path / "client_state")
    assert service.link(str(project))["entrypoint"] == "designer_addon"


def test_new_project_auto_discovers_entrypoint_after_first_commit(tmp_path):
    project = tmp_path / "new_repository"
    project.mkdir()
    service = AddonProjectService(tmp_path / "client_state")
    description = service.link(str(project))
    assert description["entrypoint"] == ""

    staged = service.stage_patch(description["project_id"], {
        "expected_revision": description["revision"],
        "changes": [{
            "path": "studio_addon/__init__.py",
            "expected_sha256": None,
            "content": (
                "bl_info = {'name': 'Studio'}\n"
                "def register():\n    pass\n"
                "def unregister():\n    pass\n"
            ),
        }],
    })
    committed = service.commit_patch(description["project_id"], staged["proposal_id"])
    assert committed["entrypoint"] == "studio_addon"
    manifest = json.loads(
        (project / ".mixar" / "addon-project.json").read_text(encoding="utf-8")
    )
    assert manifest["entrypoint"] == "studio_addon"


def test_commit_preserves_existing_file_permissions(linked_project):
    service, project, description = linked_project
    target = project / "operators.py"
    target.chmod(0o640)
    description = service.describe(description["project_id"])
    record = next(item for item in description["files"] if item["path"] == "operators.py")
    staged = service.stage_patch(description["project_id"], {
        "expected_revision": description["revision"],
        "changes": [{
            "path": "operators.py",
            "expected_sha256": record["sha256"],
            "content": "def answer():\n    return 42\n",
        }],
    })
    service.commit_patch(description["project_id"], staged["proposal_id"])
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
