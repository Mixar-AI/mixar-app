# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The held-open ``render_viewport(quality="final")`` tool call.

A script result of ``{"__deferred_preview__": key}`` must not be answered by
the executor tick; a timer poller answers the ORIGINAL request id with the
preview's terminal state, the queue keeps draining meanwhile, the liveness
probe reports the pending call, and a file load or a bounded wait fails it.
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from mixar.modules.common.agent_execution.request import ExecutionRequest

ROOT = Path(__file__).resolve().parents[1]
CHAT_ROOT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"
KEY = "c" * 32


def _fake_client(monkeypatch):
    client = MagicMock()
    client.is_connected = True
    jc = ModuleType("mixar.modules.space_mixie_chat.core.jsonrpc_client")
    jc.get_jsonrpc_client = lambda: client
    monkeypatch.setitem(sys.modules, jc.__name__, jc)
    return client


@pytest.fixture
def deferral(monkeypatch):
    from mixar.modules.space_mixie_chat.core import preview_deferral as module

    fake = MagicMock(name="bpy")
    fake.app.handlers.load_pre = []
    fake.app.timers.is_registered.return_value = False
    monkeypatch.setattr(module, "bpy", fake)
    polls = {"value": {"job_id": KEY, "status": "running", "scene_session": "s"}}
    monkeypatch.setattr(module.preview_render, "poll", lambda key: dict(polls["value"]))
    monkeypatch.setattr(module, "_pending", None)
    module.polls = polls
    yield module
    module._pending = None


def _req(request_id="req-1", tool_name="render_viewport"):
    return ExecutionRequest(request_id=request_id, script="", tool_name=tool_name,
                            session_id="sess")


def test_deferral_registers_a_poller_and_holds_the_request(deferral, monkeypatch):
    client = _fake_client(monkeypatch)
    assert deferral.defer_response(_req(), KEY) is True
    deferral.bpy.app.timers.register.assert_called_once()
    assert deferral.bpy.app.timers.register.call_args[0][0] is deferral._tick
    assert deferral._on_load_pre in deferral.bpy.app.handlers.load_pre
    client.queue_response.assert_not_called()
    assert deferral._tick() == deferral.POLL_INTERVAL_S  # still running
    client.queue_response.assert_not_called()


def test_terminal_poll_answers_the_original_request_once(deferral, monkeypatch):
    client = _fake_client(monkeypatch)
    deferral.defer_response(_req("req-7"), KEY)
    deferral.polls["value"] = {
        "job_id": KEY, "status": "done", "image_url": "data:image/png;base64,AA==",
        "scene_advanced": False, "scene_session": "s",
        "render": {"engine": "CYCLES", "device": "CPU", "samples": 32,
                   "width": 768, "height": 576, "elapsed_seconds": 1.5},
    }
    assert deferral._tick() is None
    client.queue_response.assert_called_once()
    request_id, result = client.queue_response.call_args[0]
    assert request_id == "req-7"
    assert result["success"] is True and result["status"] == "done"
    assert result["image_url"].startswith("data:image/png;base64,")
    assert result["render"]["samples"] == 32 and result["scene_session"] == "s"
    assert deferral.get_pending_inflight() is None
    assert deferral._tick() is None  # nothing pending: never answers twice
    client.queue_response.assert_called_once()


@pytest.mark.parametrize("status", ["cancelled", "lost", "failed"])
def test_every_terminal_state_is_an_ordinary_tool_result(deferral, monkeypatch, status):
    client = _fake_client(monkeypatch)
    deferral.defer_response(_req(), KEY)
    deferral.polls["value"] = {"job_id": KEY, "status": status, "error": "x"}
    deferral._tick()
    _rid, result = client.queue_response.call_args[0]
    assert result["success"] is True and result["status"] == status
    assert "image_url" not in result


def test_bounded_wait_times_out_and_leaves_the_job_alone(deferral, monkeypatch):
    client = _fake_client(monkeypatch)
    deferral.defer_response(_req("req-2"), KEY)
    started = deferral._pending["started"]
    monkeypatch.setattr(deferral.time, "monotonic",
                        lambda: started + deferral.PREVIEW_DEFERRED_MAX_S + 1)
    assert deferral._tick() is None
    request_id, result = client.queue_response.call_args[0]
    assert request_id == "req-2"
    assert result == {"job_id": KEY, "status": "running", "scene_session": "s",
                      "success": False, "error": "preview_timeout"}
    assert deferral._pending is None


def test_liveness_reports_the_pending_tool_call_with_its_own_name(deferral, monkeypatch):
    _fake_client(monkeypatch)
    deferral.defer_response(_req("req-3", tool_name="render_viewport"), KEY)
    info = deferral.get_pending_inflight()
    assert info["tool_name"] == "render_viewport"
    assert info["request_id"] == "req-3" and info["session_id"] == "sess"
    assert info["job_id"] == KEY and info["elapsed_s"] >= 0
    assert "render_preview" not in (CHAT_ROOT / "core/preview_deferral.py").read_text()


def test_executor_liveness_falls_back_to_the_pending_deferral(deferral, monkeypatch):
    _fake_client(monkeypatch)
    from mixar.modules.space_mixie_chat.core import main_thread_executor as mte

    monkeypatch.setattr(mte, "_inflight", None)
    assert mte.get_inflight_script() is None
    deferral.defer_response(_req("req-4"), KEY)
    assert mte.get_inflight_script()["request_id"] == "req-4"


def test_file_load_fails_the_pending_request_immediately(deferral, monkeypatch):
    client = _fake_client(monkeypatch)
    deferral.defer_response(_req("req-5"), KEY)
    deferral.bpy.app.timers.is_registered.return_value = True
    deferral._on_load_pre(None)
    request_id, result = client.queue_response.call_args[0]
    assert request_id == "req-5"
    assert result == {"success": False, "error": "scene_unavailable", "job_id": KEY}
    deferral.bpy.app.timers.unregister.assert_called_once_with(deferral._tick)
    assert deferral._tick() is None
    client.queue_response.assert_called_once()


def test_a_second_deferral_supersedes_the_first(deferral, monkeypatch):
    client = _fake_client(monkeypatch)
    deferral.defer_response(_req("req-old"), KEY)
    deferral.defer_response(_req("req-new"), KEY)
    request_id, result = client.queue_response.call_args[0]
    assert request_id == "req-old" and result["error"] == "preview_superseded"
    assert deferral.get_pending_inflight()["request_id"] == "req-new"


def test_deferred_key_is_only_read_from_successful_dict_results(deferral):
    assert deferral.deferred_preview_key({"success": True, "__deferred_preview__": KEY}) == KEY
    # The backend's own convention: print("__RESULT__" + json.dumps(...)).
    printed = {"success": True,
               "output": 'starting\n__RESULT__{"__deferred_preview__": "%s"}\n' % KEY}
    assert deferral.deferred_preview_key(printed) == KEY
    assert deferral.deferred_preview_key({"success": True, "output": "__RESULT__not json"}) is None
    assert deferral.deferred_preview_key({"success": True, "output": '__RESULT__{"status": "failed"}'}) is None
    assert deferral.deferred_preview_key({"success": False, "__deferred_preview__": KEY}) is None
    assert deferral.deferred_preview_key({"success": True, "__deferred_preview__": 3}) is None
    assert deferral.deferred_preview_key({"success": True}) is None
    assert deferral.deferred_preview_key(None) is None


# --------------------------------------------------------------------------
# The executor tick: skip respond, keep draining
# --------------------------------------------------------------------------


def _load_executor(monkeypatch):
    for name in ("bpy", "bmesh", "mathutils", "bpy_extras", "imbuf"):
        monkeypatch.setitem(sys.modules, name, MagicMock(name=name))
    for name, path in (
        ("mixar", ROOT / "src/scripts/mixar"),
        ("mixar.modules", ROOT / "src/scripts/mixar/modules"),
        ("mixar.modules.space_mixie_chat", CHAT_ROOT),
        ("mixar.modules.space_mixie_chat.core", CHAT_ROOT / "core"),
    ):
        package = ModuleType(name)
        package.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, package)
    module_name = "mixar.modules.space_mixie_chat.core.main_thread_executor"
    spec = importlib.util.spec_from_file_location(
        module_name, CHAT_ROOT / "core" / "main_thread_executor.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def executor(monkeypatch, deferral):
    module = _load_executor(monkeypatch)
    monkeypatch.setattr(module, "_execution_gate_until", 0.0)
    monkeypatch.setattr(module, "_held", None)
    while not module._request_queue.empty():
        module._request_queue.get_nowait()
    for name, attrs in (
        ("queue_processor", {"drain_pending_events": lambda: None}),
        ("lane_scene_sweep", {"schedule_lane_scene_sweep": lambda: None}),
        ("steps_recorder", {"record_step_start": lambda *a: None,
                            "record_step_end": lambda *a: None}),
    ):
        stub = ModuleType("mixar.modules.space_mixie_chat.core." + name)
        for attr, value in attrs.items():
            setattr(stub, attr, value)
        monkeypatch.setitem(sys.modules, stub.__name__, stub)
    session_mod = ModuleType("mixar.modules.space_mixie_chat.core.session")
    session = MagicMock()
    session.has_active_session.return_value = True
    session_mod.get_session_manager = lambda: session
    monkeypatch.setitem(sys.modules, session_mod.__name__, session_mod)
    monkeypatch.setattr(module, "route_request", lambda *a: (None, False, None))
    monkeypatch.setattr(module, "archive_history", lambda *a: None)
    monkeypatch.setattr(module, "restore_after", lambda *a: None)
    fake_executor = MagicMock()
    fake_executor._execution_lock.locked.return_value = False
    monkeypatch.setattr(module, "get_executor", lambda: fake_executor)
    return module


def _queue(module, request_id):
    module._request_queue.put_nowait((request_id, "x", "render_viewport", "sess", None, None))


def test_deferred_result_skips_respond_and_the_queue_keeps_draining(
    executor, deferral, monkeypatch
):
    client = _fake_client(monkeypatch)
    results = {
        "req-1": {"success": True, "__deferred_preview__": KEY},
        "req-2": {"success": True, "objects": 3},
    }
    monkeypatch.setattr(executor.pump, "execute_request",
                        lambda req, ex, on_success=None: dict(results[req.request_id]))
    _queue(executor, "req-1")
    _queue(executor, "req-2")

    assert executor._process_one_request() == 0.50  # more work queued
    client.queue_response.assert_not_called()  # req-1 is held open
    assert executor.get_inflight_script()["request_id"] == "req-1"
    deferral.bpy.app.timers.register.assert_called_once()

    executor._process_one_request()  # req-2 executes while req-1 is pending
    client.queue_response.assert_called_once_with("req-2", {"success": True, "objects": 3})

    deferral.polls["value"] = {"job_id": KEY, "status": "done", "image_url": "data:image/png;base64,AA=="}
    assert deferral._tick() is None
    assert client.queue_response.call_args[0][0] == "req-1"
    assert client.queue_response.call_args[0][1]["status"] == "done"
    assert executor.get_inflight_script() is None


def test_executor_flush_fails_a_pending_deferral(executor, deferral, monkeypatch):
    client = _fake_client(monkeypatch)
    deferral.defer_response(_req("req-9"), KEY)
    executor.cleanup()
    request_id, result = client.queue_response.call_args[0]
    assert request_id == "req-9" and result["error"] == "executor_reset"
