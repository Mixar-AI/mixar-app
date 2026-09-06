# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent scripts must not mutate the scene under a running render job.

The agent's final render is fire-and-forget (Blender's F12 job thread), so
the next agent script — same turn's verification canary, or the user's next
message — used to run against the datablocks the renderer was reading. That
is Blender's documented "modifying data during rendering" crash: a segfault,
never an exception. Two guards, both pinned here:

* the sandbox executor HOLDS the head-of-queue script while a RENDER job is
  alive (bounded, then a structured error — never an opaque RPC timeout);
* the final-render operator turns Lock Interface on for the job and restores
  the user's setting afterwards (the same guard the splat render path uses).
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHAT_ROOT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"


# --------------------------------------------------------------------------
# render_job_running()
# --------------------------------------------------------------------------


def test_probe_reads_only_a_literal_true_as_running(monkeypatch):
    from mixar.modules.common.utils import render_jobs

    fake_bpy = MagicMock(name="bpy")
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    # A MagicMock return (the test-suite bpy) is truthy but is NOT a render.
    assert render_jobs.render_job_running() is False
    fake_bpy.app.is_job_running.return_value = True
    assert render_jobs.render_job_running() is True
    fake_bpy.app.is_job_running.assert_called_with("RENDER")
    fake_bpy.app.is_job_running.return_value = False
    assert render_jobs.render_job_running() is False


def test_probe_fails_open_when_the_api_is_missing(monkeypatch):
    from mixar.modules.common.utils import render_jobs

    fake_bpy = MagicMock(name="bpy")
    fake_bpy.app.is_job_running.side_effect = AttributeError("old build")
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    assert render_jobs.render_job_running() is False


# --------------------------------------------------------------------------
# main_thread_executor: hold, then refuse
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
def executor(monkeypatch):
    module = _load_executor(monkeypatch)
    # Timer registration is a no-op under the mock; drive ticks by hand.
    monkeypatch.setattr(module, "_execution_gate_until", 0.0)
    monkeypatch.setattr(module, "_render_wait_started", None)
    monkeypatch.setattr(module, "_held", None)
    while not module._request_queue.empty():
        module._request_queue.get_nowait()
    # drain_pending_events is imported lazily from queue_processor.
    qp = ModuleType("mixar.modules.space_mixie_chat.core.queue_processor")
    qp.drain_pending_events = lambda: None
    monkeypatch.setitem(sys.modules, qp.__name__, qp)
    return module


def _queue(module, request_id="req-1"):
    module._request_queue.put_nowait(
        (request_id, "print('x')", "some_tool", "sess", None, None)
    )


def _fake_client(monkeypatch):
    client = MagicMock()
    client.is_connected = True
    jc = ModuleType("mixar.modules.space_mixie_chat.core.jsonrpc_client")
    jc.get_jsonrpc_client = lambda: client
    monkeypatch.setitem(sys.modules, jc.__name__, jc)
    return client


def test_script_is_held_while_a_render_job_runs(executor, monkeypatch):
    client = _fake_client(monkeypatch)
    monkeypatch.setattr(executor, "render_job_running", lambda: True)
    _queue(executor)

    assert executor._process_one_request() == executor.TIMER_INTERVAL
    # Still at the head of the queue, nothing executed, nothing answered.
    assert executor._held is not None
    assert executor._held[0] == "req-1"
    assert executor._render_wait_started is not None
    client.queue_response.assert_not_called()
    assert executor.get_inflight_script() is None

    # Later ticks keep holding (FIFO preserved) while the render is alive.
    assert executor._process_one_request() == executor.TIMER_INTERVAL
    client.queue_response.assert_not_called()


def test_held_script_is_refused_with_a_structured_error_after_the_cap(
    executor, monkeypatch
):
    client = _fake_client(monkeypatch)
    monkeypatch.setattr(executor, "render_job_running", lambda: True)
    _queue(executor)
    executor._process_one_request()

    # Pretend the render has outlived the cap.
    executor._render_wait_started -= executor.RENDER_WAIT_MAX_S + 1
    ret = executor._process_one_request()

    client.queue_response.assert_called_once()
    req_id, payload = client.queue_response.call_args[0]
    assert req_id == "req-1"
    assert payload["success"] is False
    assert payload["error"] == executor.RENDER_IN_PROGRESS_ERROR
    assert "render" in payload["error"].lower()
    # Refused request is dropped; the gate resets for the next one.
    assert executor._held is None
    assert executor._render_wait_started is None
    assert ret is None  # queue empty -> timer stops


def test_hold_lifts_the_moment_the_render_finishes(executor, monkeypatch):
    _fake_client(monkeypatch)
    running = {"v": True}
    monkeypatch.setattr(executor, "render_job_running", lambda: running["v"])
    _queue(executor)
    assert executor._process_one_request() == executor.TIMER_INTERVAL
    assert executor._held is not None

    running["v"] = False
    # Stop before the session lookup: a stale-session drop is the cheapest
    # proof the request left the hold and proceeded down the normal path.
    session_mod = ModuleType("mixar.modules.space_mixie_chat.core.session")
    session = MagicMock()
    session.has_active_session.return_value = False
    session_mod.get_session_manager = lambda: session
    monkeypatch.setitem(sys.modules, session_mod.__name__, session_mod)
    sweep = ModuleType("mixar.modules.space_mixie_chat.core.lane_scene_sweep")
    sweep.schedule_lane_scene_sweep = lambda: None
    monkeypatch.setitem(sys.modules, sweep.__name__, sweep)

    executor._process_one_request()
    assert executor._held is None
    assert executor._render_wait_started is None


def test_render_wait_cap_is_under_the_backend_script_timeout(executor):
    # decorator.execute_script_on_instance defaults to 30 s; a hold longer
    # than that turns a clean error into an opaque RPC timeout.
    assert 0 < executor.RENDER_WAIT_MAX_S < 30


# --------------------------------------------------------------------------
# agent_final_render_ops: Lock Interface for the job
# --------------------------------------------------------------------------


def _ops_module():
    for dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
        sys.modules.setdefault(dep, MagicMock(name=dep))
    from mixar.modules.space_mixie_chat.ui.operators import agent_final_render_ops

    return agent_final_render_ops


def _scene(lock=False):
    scene = MagicMock()
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_percentage = 100
    scene.render.filepath = "/tmp/x"
    scene.render.image_settings.file_format = "PNG"
    scene.render.use_lock_interface = lock
    scene.world = None
    return scene


def test_final_render_locks_the_interface_and_restores_it(monkeypatch):
    ops = _ops_module()
    fake_bpy = MagicMock(name="bpy")
    fake_bpy.data.lights = []
    fake_bpy.data.materials = []
    monkeypatch.setattr(ops, "bpy", fake_bpy)
    monkeypatch.setattr(ops, "_resolve_engine", lambda engine: None)

    scene = _scene(lock=False)
    saved, _note, _orig, _capped = ops._apply_settings(
        scene, "current", 0, 0, "current", "/tmp/out.png"
    )
    assert scene.render.use_lock_interface is True
    assert saved["lock"] is False

    ops._restore_settings(scene, saved)
    assert scene.render.use_lock_interface is False


def test_final_render_keeps_a_user_lock_on(monkeypatch):
    ops = _ops_module()
    fake_bpy = MagicMock(name="bpy")
    fake_bpy.data.lights = []
    fake_bpy.data.materials = []
    monkeypatch.setattr(ops, "bpy", fake_bpy)
    monkeypatch.setattr(ops, "_resolve_engine", lambda engine: None)

    scene = _scene(lock=True)
    saved, *_ = ops._apply_settings(scene, "current", 0, 0, "current", "/tmp/o.png")
    ops._restore_settings(scene, saved)
    assert scene.render.use_lock_interface is True


def test_restore_tolerates_a_pre_lock_saved_dict():
    ops = _ops_module()
    scene = _scene(lock=False)
    ops._restore_settings(
        scene, {"engine": "CYCLES", "rp": 50, "fp": "/tmp/a", "ff": "PNG"}
    )
    assert scene.render.use_lock_interface is False


# --------------------------------------------------------------------------
# on_connected must not walk bpy.data on the WebSocket thread
# --------------------------------------------------------------------------


def test_orphaned_turn_check_is_marshalled_to_the_main_thread():
    """``on_connected`` runs on the WebSocket receive thread; the orphaned-turn
    check iterates ``bpy.data.scenes`` and reads scene RNA, so it must reach
    the main thread first. Calling it inline raced the main thread's lane
    scene add/remove on every mid-turn reconnect."""
    src = (CHAT_ROOT / "core/connection_manager.py").read_text()
    start = src.index("def on_connected()")
    end = src.index("def on_disconnected(", start)
    block = src[start:end]
    assert "run_on_main_thread(check_orphaned_turns)" in block
    assert "\n                    check_orphaned_turns()\n" not in block


def test_sidecar_instance_read_goes_through_the_main_thread():
    src = (ROOT / "src/scripts/mixar/modules/connector/core/sidecar.py").read_text()
    start = src.index("def _instance()")
    end = src.index("def _health()", start)
    block = src[start:end]
    assert "_run_on_main(_read)" in block
