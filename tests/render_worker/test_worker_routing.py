# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Routing of agent previews and export packages to the background worker.

The wire contract is unchanged: a preview still answers ``__deferred_preview__``
and then the same terminal dict; an export package's script still prints its
``__RESULT__``, which now carries ``{"__deferred_job__": key}`` and is answered
on the same request id with ``export_package``'s ordinary return value.
"""

import json
import sys
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mixar.modules.common.agent_execution.request import ExecutionRequest

KEY = "d" * 32


def _fake_client(monkeypatch):
    client = MagicMock()
    client.is_connected = True
    jc = ModuleType("mixar.modules.space_mixie_chat.core.jsonrpc_client")
    jc.get_jsonrpc_client = lambda: client
    monkeypatch.setitem(sys.modules, jc.__name__, jc)
    return client


def _req(request_id="req-1", tool_name="export_asset", session="sess"):
    return ExecutionRequest(request_id=request_id, script="", tool_name=tool_name,
                            session_id=session)


def _sent(client):
    return client.queue_response.call_args[0][1] if client.queue_response.call_args else None


@pytest.fixture
def deferral(monkeypatch):
    from mixar.modules.space_mixie_chat.core import preview_deferral as module

    fake = MagicMock(name="bpy")
    fake.app.handlers.load_pre = []
    fake.app.timers.is_registered.return_value = False
    monkeypatch.setattr(module, "bpy", fake)
    monkeypatch.setattr(module, "_pending", None)
    monkeypatch.setattr(module, "_jobs", {})
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", "0")
    yield module


# --------------------------------------------------------------------------
# preview_deferral: worker jobs held open, any number at once
# --------------------------------------------------------------------------

def test_a_printed_deferred_job_key_is_read_like_the_preview_key(deferral):
    printed = {"success": True, "output": 'x\n__RESULT__{"__deferred_job__": "k1", "success": true}\n'}
    assert deferral.deferred_job_key(printed) == "k1"
    assert deferral.deferred_preview_key(printed) is None
    assert deferral.deferred_job_key({"success": False, "__deferred_job__": "k1"}) is None


def test_a_job_is_answered_once_with_the_owner_result(deferral, monkeypatch):
    client = _fake_client(monkeypatch)
    state = {"value": {"status": "running"}}
    req = _req()
    assert deferral.defer_job(req, "k1", poll=lambda key: state["value"], max_s=60,
                              initial_result={"success": True, "__deferred_job__": "k1",
                                              "output": "__RESULT__{}"})
    entry = deferral._jobs["k1"]
    assert entry["timer"]() == deferral.POLL_INTERVAL_S
    client.queue_response.assert_not_called()
    state["value"] = {"status": "done", "result": {"success": True, "main_file": "chair.glb",
                                                   "files": ["chair.glb"]}}
    assert entry["timer"]() is None
    client.queue_response.assert_called_once()
    reply = _sent(client)
    assert reply["success"] is True and reply["main_file"] == "chair.glb"
    assert "__deferred_job__" not in reply and "output" not in reply
    assert not deferral._jobs
    assert entry["timer"]() is None  # a late tick answers nothing


def test_jobs_and_a_preview_are_held_side_by_side(deferral, monkeypatch):
    _fake_client(monkeypatch)
    monkeypatch.setattr(deferral.preview_render, "poll", lambda key: {"status": "running"})
    deferral.defer_response(_req("p", "render_viewport"), KEY)
    deferral.defer_job(_req("e1"), "k1", poll=lambda key: {"status": "running"}, max_s=60)
    deferral.defer_job(_req("e2"), "k2", poll=lambda key: {"status": "running"}, max_s=60)
    assert deferral._pending["key"] == KEY and set(deferral._jobs) == {"k1", "k2"}
    assert deferral.get_pending_inflight()["request_id"] == "p"


def test_liveness_reports_a_job_when_no_preview_is_pending(deferral, monkeypatch):
    _fake_client(monkeypatch)
    deferral.defer_job(_req("e1"), "k1", poll=lambda key: {"status": "running"}, max_s=60)
    info = deferral.get_pending_inflight()
    assert info["request_id"] == "e1" and info["tool_name"] == "export_asset"


def test_a_session_flush_fails_and_cancels_only_its_jobs(deferral, monkeypatch):
    client = _fake_client(monkeypatch)
    cancelled = []
    deferral.defer_job(_req("mine", session="sess"), "k1", poll=lambda key: {"status": "running"},
                       cancel=cancelled.append, max_s=60)
    deferral.defer_job(_req("other", session="other"), "k2", poll=lambda key: {"status": "running"},
                       cancel=cancelled.append, max_s=60)
    assert deferral.fail_pending("executor_reset", session_id="sess") is True
    assert cancelled == ["k1"] and set(deferral._jobs) == {"k2"}
    assert _sent(client)["error"] == "executor_reset"


def test_a_file_load_fails_every_job(deferral, monkeypatch):
    _fake_client(monkeypatch)
    cancelled = []
    deferral.defer_job(_req("e1"), "k1", poll=lambda key: {"status": "running"},
                       cancel=cancelled.append, max_s=60)
    deferral._on_load_pre()
    assert cancelled == ["k1"] and not deferral._jobs


def test_a_job_over_its_bound_is_cancelled_and_answered(deferral, monkeypatch):
    client = _fake_client(monkeypatch)
    cancelled = []
    deferral.defer_job(_req("e1"), "k1", poll=lambda key: {"status": "running"},
                       cancel=cancelled.append, max_s=0.0)
    deferral._jobs["k1"]["timer"]()
    assert cancelled == ["k1"]
    assert _sent(client)["error"] == "worker_job_timeout"


def test_the_executor_holds_a_worker_job_reply(monkeypatch):
    from mixar.modules.space_mixie_chat.core import main_thread_executor as mte
    from mixar.modules.space_mixie_chat.core import preview_deferral as module
    calls = {}
    monkeypatch.setattr(module, "defer_job", lambda req, key, **kw: calls.setdefault("key", key) or True)
    held = mte._defer_worker_job(_req(), {"success": True, "__deferred_job__": "k9"}, None)
    assert held and calls["key"] == "k9"
    assert mte._defer_worker_job(_req(), {"success": True, "files": []}, None) is False


def test_only_the_gui_executor_accepts_deferred_jobs():
    from mixar.modules.space_mixie_chat.core import main_thread_executor as mte
    assert mte.accepts_deferred_jobs() is False
    src = open(mte.__file__, encoding="utf-8").read()
    body = src[src.index("def _execute_dequeued_request("):src.index("def _defer_worker_job(")]
    assert "_deferrable_depth += 1" in body and "_deferrable_depth -= 1" in body


# --------------------------------------------------------------------------
# export_package: routed to the worker from the executor, else in-process
# --------------------------------------------------------------------------

@pytest.fixture
def pkg(monkeypatch, tmp_path):
    from mixar.modules.space_mixie_chat.core import export_package as module
    from mixar.modules.common.render_worker import snapshot, supervisor

    fake = MagicMock(name="bpy")
    fake.app.background = False
    fake.data.filepath = str(tmp_path / "proj" / "scene.blend")
    mesh = SimpleNamespace(type="MESH", name="Chair")
    scene = SimpleNamespace(name="Scene", objects={"Chair": mesh},
                            view_layers=SimpleNamespace(get=lambda name: None))
    fake.context.scene = scene
    fake.context.view_layer = SimpleNamespace(name="ViewLayer")
    monkeypatch.setattr(module, "bpy", fake)
    monkeypatch.setattr(module, "_worker_jobs", {})
    monkeypatch.setattr(module, "_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(module, "destination", lambda where, sub=None: str(tmp_path / "out"))
    record = {"folder": str(tmp_path / "snap"), "path": str(tmp_path / "snap" / "s.blend"),
              "images": "", "image_count": 0, "bytes": 10, "save_s": 0.1, "images_s": 0.0}
    monkeypatch.setattr(snapshot, "write", lambda purpose: dict(record))
    monkeypatch.setattr(snapshot, "acquire", lambda rec: None)
    monkeypatch.setattr(snapshot, "release", lambda rec: None)
    jobs = {}
    monkeypatch.setattr(supervisor, "root_dir", lambda: str(tmp_path))
    monkeypatch.setattr(supervisor, "available", lambda: True)
    monkeypatch.setattr(supervisor, "submit",
                        lambda kind, message, timeout_s: jobs.setdefault("j1", message) and "j1")
    monkeypatch.setattr(supervisor, "forget", lambda job_id: None)
    state = {"value": {"state": "running"}}
    monkeypatch.setattr(supervisor, "poll", lambda job_id: dict(state["value"]))
    from mixar.modules.space_mixie_chat.core import main_thread_executor as mte
    monkeypatch.setattr(mte, "_deferrable_depth", 1)
    module.submitted, module.state = jobs, state
    yield module


def test_an_executor_script_gets_a_deferred_key_and_the_worker_the_call(pkg):
    reply = pkg.export_package(["Chair"], "glb", where="project", texture_tiers=(512,))
    key = reply["__deferred_job__"]
    assert len(key) == 32
    message = pkg.submitted["j1"]
    assert message["kind"] == "export" and message["scene"] == "Scene"
    assert message["params"]["kwargs"]["names"] == ["Chair"]
    assert message["params"]["kwargs"]["texture_tiers"] == [512]
    assert message["params"]["project_dir"].endswith("proj"), "the user's folder, not the snapshot's"
    assert pkg.poll_job(key) == {"status": "running"}


def test_the_worker_result_is_the_reply(pkg, tmp_path):
    key = pkg.export_package(["Chair"])["__deferred_job__"]
    out = tmp_path / "result.json"
    out.write_text(json.dumps({"success": True, "main_file": "Chair.glb", "files": ["Chair.glb"]}))
    pkg.state["value"] = {"state": "done", "out": str(out), "attempts": 1}
    done = pkg.poll_job(key)
    assert done == {"status": "done", "result": {"success": True, "main_file": "Chair.glb",
                                                 "files": ["Chair.glb"]}}
    assert not out.exists()
    assert pkg.poll_job(key)["result"]["success"] is False  # unknown afterwards


def test_two_crashes_fail_the_package_with_a_plain_message(pkg):
    key = pkg.export_package(["Chair"])["__deferred_job__"]
    pkg.state["value"] = {"state": "failed", "error": "worker_crashed", "attempts": 2}
    result = pkg.poll_job(key)["result"]
    assert result["success"] is False and "crashed twice" in result["error"]
    assert "/" not in result["error"]


def test_a_worker_that_never_started_builds_the_package_here(pkg, monkeypatch):
    key = pkg.export_package(["Chair"])["__deferred_job__"]
    pkg.state["value"] = {"state": "failed", "error": "worker_unavailable", "attempts": 0}
    monkeypatch.setattr(pkg, "_export_in_process", lambda **kw: {"files": ["Chair.glb"]})
    assert pkg.poll_job(key)["result"] == {"files": ["Chair.glb"], "success": True}
    assert pkg.last_worker_job()["fallback"] == "in_process"


def test_outside_the_executor_the_package_is_built_in_process(pkg, monkeypatch):
    from mixar.modules.space_mixie_chat.core import main_thread_executor as mte
    monkeypatch.setattr(mte, "_deferrable_depth", 0)
    monkeypatch.setattr(pkg, "_export_in_process", lambda **kw: {"built": kw["names"]})
    assert pkg.export_package(["Chair"]) == {"built": ["Chair"]}
    assert not pkg.submitted


def test_inside_a_worker_the_package_is_built_in_process(pkg, monkeypatch):
    pkg.bpy.app.background = True
    monkeypatch.setattr(pkg, "_export_in_process", lambda **kw: {"built": True})
    assert pkg.export_package(["Chair"]) == {"built": True}


def test_a_bad_call_fails_at_once_as_before(pkg):
    with pytest.raises(KeyError):
        pkg.export_package(["Missing"])
    with pytest.raises(ValueError):
        pkg.export_package(["Chair"], "obj")
    assert not pkg.submitted


def test_the_project_destination_follows_the_users_file_in_a_worker(monkeypatch, tmp_path):
    from mixar.modules.space_mixie_chat.core import export_package as module
    fake = MagicMock(name="bpy")
    fake.data.filepath = str(tmp_path / "snapshots" / "mixar_worker_snapshot_1.blend")
    monkeypatch.setattr(module, "bpy", fake)
    module.set_project_folder(str(tmp_path / "user"))
    try:
        assert module.destination("project") == str(tmp_path / "user")
        module.set_project_folder("")  # the user's file was never saved
        assert "Mixar Exports" in module.destination("project")
    finally:
        module.set_project_folder(None)


# --------------------------------------------------------------------------
# preview_render: the worker reply carries what the in-process reply carries
# --------------------------------------------------------------------------

@pytest.fixture
def preview(monkeypatch, tmp_path):
    from mixar.modules.space_mixie_chat.core import preview_render as module
    from mixar.modules.common.render_worker import snapshot, supervisor
    monkeypatch.setattr(module, "_job", None)
    monkeypatch.setattr(module, "_records", {})
    monkeypatch.setattr(module, "_revision", 5)
    monkeypatch.setattr(module, "bpy", MagicMock(name="bpy"))
    monkeypatch.setattr(snapshot, "release", lambda rec: None)
    monkeypatch.setattr(supervisor, "forget", lambda job_id: None)
    state = {"value": {"state": "running"}}
    monkeypatch.setattr(supervisor, "poll", lambda job_id: dict(state["value"]))
    module.state = state
    yield module


def _worker_job(module, **extra):
    job = {"key": KEY, "scene": SimpleNamespace(name="Scene"), "worker": "j1", "snapshot": {},
           "revision": 5, "scene_session": "sess", "started_at": time.monotonic() - 2,
           "render": {"engine": "CYCLES", "width": 768, "height": 576}, "args": {"inspection": None},
           "finishing": False, "view_layer": "ViewLayer"}
    job.update(extra)
    module._job = job
    return job


def test_a_running_worker_job_polls_as_running(preview):
    _worker_job(preview)
    value = preview.poll(KEY)
    assert value["status"] == "running" and value["scene_session"] == "sess"


def test_a_done_worker_job_publishes_the_same_reply_as_a_native_one(preview, tmp_path):
    _worker_job(preview)
    out = tmp_path / "p.json"
    out.write_text(json.dumps({"job_id": KEY, "status": "done", "image_url": "data:image/png;base64,AA==",
                               "render": {"engine": "CYCLES", "device": "GPU", "samples": 32,
                                          "width": 768, "height": 576, "elapsed_seconds": None}}))
    preview.state["value"] = {"state": "done", "out": str(out), "attempts": 1}
    value = preview.poll(KEY)
    assert value["status"] == "done" and value["image_url"].startswith("data:image/png")
    assert value["scene_session"] == "sess" and value["render_revision"] == 5
    assert value["scene_advanced"] is False and value["scene_revision"] == 5
    assert value["render"]["device"] == "GPU" and value["render"]["elapsed_seconds"] >= 2
    assert preview._job is None


def test_a_scene_change_during_a_worker_job_reads_as_advanced(preview, tmp_path, monkeypatch):
    _worker_job(preview)
    out = tmp_path / "p.json"
    out.write_text(json.dumps({"job_id": KEY, "status": "done", "image_url": "data:,", "render": {}}))
    preview.state["value"] = {"state": "done", "out": str(out)}
    monkeypatch.setattr(preview, "_revision", 9)
    assert preview.poll(KEY)["scene_advanced"] is True


def test_a_twice_crashed_preview_fails_with_a_fixed_code(preview):
    _worker_job(preview, args={"inspection": {"view": "hero"}})
    preview.state["value"] = {"state": "failed", "error": "worker_crashed", "attempts": 2}
    value = preview.poll(KEY)
    assert value["status"] == "failed" and value["error"] == "render_worker_crashed"
    assert value["success"] is False


def test_a_preview_whose_worker_never_started_renders_natively(preview, monkeypatch):
    _worker_job(preview, scene=SimpleNamespace(name="Scene", view_layers={}))
    preview.bpy.context.window_manager.windows = [object()]
    preview.state["value"] = {"state": "failed", "error": "worker_unavailable", "attempts": 0}
    calls = {}

    def native(context, key, source, session, win, **args):
        calls.update(key=key, session=session, args=args)
        return {"job_id": key, "status": "running"}

    monkeypatch.setattr(preview, "_start_native", native)
    value = preview.poll(KEY)
    assert value["status"] == "running" and calls["key"] == KEY and calls["session"] == "sess"
    assert preview.last_worker_job()["fallback"] == "in_process"


def test_undo_never_settles_a_worker_job(preview, monkeypatch):
    job = _worker_job(preview)
    finished = []
    monkeypatch.setattr(preview, "_finish", lambda *a, **k: finished.append(a))
    preview._before_undo()
    assert not finished and preview._job is job


def test_a_file_load_cancels_the_worker_job(preview, monkeypatch):
    from mixar.modules.common.render_worker import supervisor
    _worker_job(preview)
    cancelled = []
    monkeypatch.setattr(supervisor, "cancel", cancelled.append)
    preview._before_load(None)
    assert cancelled == ["j1"] and preview._job is None


def test_the_synchronous_render_lives_only_in_the_worker():
    from pathlib import Path
    from mixar.modules.common.render_worker import worker_jobs  # noqa: F401 — importable
    src = Path(worker_jobs.__file__).read_text(encoding="utf-8")
    body = src[src.index("def render_preview("):src.index("def _run_preview(")]
    assert "if not bpy.app.background:" in body and "raise RuntimeError" in body
