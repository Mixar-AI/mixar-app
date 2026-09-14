# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""agent.sandbox_control handler on the parent (v3 PR 1).

Pins the control contract the backend sender relies on: spawn is idempotent
for a live child, refresh_token RESTARTS (never a bare ack), report_resources
is bounded and never raises, and ``-sbx-{n}`` ids resolve to their parent.
"""

import os
import sys
from unittest.mock import MagicMock

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.bootstrap import sandbox_supervisor as sup  # noqa: E402


class FakeProc:
    def __init__(self, pid, alive=True):
        self.pid = pid
        self._alive = alive
        self.terminated = False

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def wait(self, timeout=None):
        return 0


def test_parent_instance_from_handles_indexed_ids():
    assert sup._parent_instance_from("inst-sbx-0") == "inst"
    assert sup._parent_instance_from("inst-sbx") == "inst"
    assert sup._parent_instance_from("inst") == "inst"


def test_refresh_token_restarts_instead_of_acking(monkeypatch):
    calls = []
    monkeypatch.setattr(sup, "shutdown_sandbox", lambda cid=None, wait=False: calls.append(("shutdown", cid, wait)) or {"success": True})
    monkeypatch.setattr(sup, "spawn_sandbox", lambda cid, ttl=None, parent=None: calls.append(("spawn", cid, parent)) or {"success": True, "pid": 99})
    out = sup.handle_sandbox_control({"action": "refresh_token", "connection_id": "p-sbx-0", "parent_instance_id": "p"})
    assert out == {"success": True, "pid": 99}
    assert calls == [("shutdown", "p-sbx-0", True), ("spawn", "p-sbx-0", "p")]
    assert sup.handle_sandbox_control({"action": "refresh_token"})["success"] is False


def test_report_resources_is_bounded_and_counts_live_children(monkeypatch):
    monkeypatch.setattr(sup, "_children", {"a-sbx-0": FakeProc(1), "a-sbx-1": FakeProc(2, alive=False)})
    monkeypatch.setattr(sup, "_available_ram_bytes", lambda: 512 * 1024 * 1024)
    out = sup.handle_sandbox_control({"action": "report_resources"})
    assert out["success"] and out["workers"] == 1
    assert out["available_ram_mb"] == 512 and out["cpu_count"] >= 1
    assert set(out) == {"success", "total_ram_mb", "available_ram_mb", "cpu_count", "workers", "platform"}


def test_report_resources_never_raises(monkeypatch):
    monkeypatch.setattr(sup, "_available_ram_bytes", lambda: 0)
    monkeypatch.setitem(sys.modules, "mixar.modules.local_models.core.platform_info", None)
    out = sup.report_resources()
    assert out["success"] and out["total_ram_mb"] == 0


def test_unknown_action_and_spawn_idempotent(monkeypatch):
    assert sup.handle_sandbox_control({"action": "dance"})["success"] is False
    live = FakeProc(4242)
    monkeypatch.setattr(sup, "_children", {"p-sbx-0": live})
    assert sup.spawn_sandbox("p-sbx-0") == {"success": True, "pid": 4242}


def test_spawn_fails_closed_without_staging_dir(monkeypatch):
    monkeypatch.setattr(sup, "_children", {})
    monkeypatch.setattr(sup, "_child_logs", {})
    import mixar.modules.common.agent_execution.paths as paths
    monkeypatch.setattr(paths, "staging_dir", lambda *_a, **_k: (_ for _ in ()).throw(OSError("denied")))
    monkeypatch.setattr("mixar.modules.auth.core.auth.get_access_token", lambda: "tok")
    monkeypatch.setattr("mixar.config.config.get_server_url", lambda: "http://example")
    out = sup.spawn_sandbox("p-sbx-0", parent_instance_id="p")
    assert out["success"] is False and out["pid"] is None
    assert "staging" in out["error"].lower()
    assert "p-sbx-0" not in sup._children


def test_refresh_token_waits_for_the_old_child(monkeypatch):
    events = []

    class SlowProc(FakeProc):
        def terminate(self):
            events.append("terminate")
            super().terminate()

        def wait(self, timeout=None):
            events.append("wait")
            return super().wait(timeout)

    children = {"p-sbx-0": SlowProc(7)}
    monkeypatch.setattr(sup, "_children", children)
    monkeypatch.setattr(sup, "_child_logs", {})
    spawned_after = []

    def fake_spawn(cid, ttl=None, parent=None):
        spawned_after.append(list(events))
        return {"success": True, "pid": 99}

    monkeypatch.setattr(sup, "spawn_sandbox", fake_spawn)
    out = sup.handle_sandbox_control(
        {"action": "refresh_token", "connection_id": "p-sbx-0", "parent_instance_id": "p"}
    )
    assert out == {"success": True, "pid": 99}
    assert events[:2] == ["terminate", "wait"]
    assert spawned_after and spawned_after[0] == ["terminate", "wait"]
