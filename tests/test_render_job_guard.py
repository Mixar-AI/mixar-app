# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A running render refuses agent scripts at once and never holds the queue.

A render started with INVOKE_DEFAULT runs on Blender's job thread against a
depsgraph registered with the open file, so a main-thread script that edits
data tags and rebuilds it mid-evaluation: 4.1.1 crashed in
``graph_tag_ids_for_visible_update`` during a scene video when moodboard
inspection created a temporary image. The executor now answers such scripts
with ``render_in_progress`` (render_gate) — never the 3.4.2 HOLD, which stalled
every turn for the whole render, and never a forced ``use_lock_interface``.
The thread-marshalling fixes from the 3.4.2 audit stay pinned here
(docs/render-job-contract.md).
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHAT_ROOT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"
PREVIEW = CHAT_ROOT / "core/preview_render.py"


# --------------------------------------------------------------------------
# main_thread_executor: a live render job is not a gate
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
    module.lanes.clear()  # the per-session script lanes (parallel scenes)
    # drain_pending_events is imported lazily from queue_processor.
    qp = ModuleType("mixar.modules.space_mixie_chat.core.queue_processor")
    qp.drain_pending_events = lambda: None
    monkeypatch.setitem(sys.modules, qp.__name__, qp)
    return module


def _queue(module, request_id="req-1"):
    from mixar.modules.common.agent_execution.request import ExecutionRequest

    module.lanes.enqueue(ExecutionRequest.from_legacy(
        (request_id, "print('x')", "some_tool", "sess", None, None)))


def _fake_client(monkeypatch):
    client = MagicMock()
    client.is_connected = True
    jc = ModuleType("mixar.modules.space_mixie_chat.core.jsonrpc_client")
    jc.get_jsonrpc_client = lambda: client
    monkeypatch.setitem(sys.modules, jc.__name__, jc)
    return client


def _stub_session_path(monkeypatch, active=False):
    session_mod = ModuleType("mixar.modules.space_mixie_chat.core.session")
    session = MagicMock()
    session.has_active_session.return_value = active
    session_mod.get_session_manager = lambda: session
    monkeypatch.setitem(sys.modules, session_mod.__name__, session_mod)
    sweep = ModuleType("mixar.modules.space_mixie_chat.core.lane_scene_sweep")
    sweep.schedule_lane_scene_sweep = lambda: None
    monkeypatch.setitem(sys.modules, sweep.__name__, sweep)


def _render(monkeypatch, kind):
    """Pretend ``kind`` owns the native RENDER job (None: no render)."""
    import importlib

    gate = importlib.import_module("mixar.modules.space_mixie_chat.core.render_gate")
    monkeypatch.setattr(gate.render_slot, "native_render_kind", lambda: kind)
    return gate


def test_a_script_is_refused_at_once_while_a_render_job_is_alive(executor, monkeypatch):
    """Answered on the first tick with a typed refusal; nothing executes, and
    the lane is not parked, so the queue keeps draining."""
    client = _fake_client(monkeypatch)
    _stub_session_path(monkeypatch, active=True)
    _render(monkeypatch, "scene_video")
    monkeypatch.setattr(executor, "get_executor", MagicMock(side_effect=AssertionError("ran")))
    monkeypatch.setattr(executor, "route_request", MagicMock(side_effect=AssertionError("routed")))
    _queue(executor, "req-1")
    _queue(executor, "req-2")

    executor._process_one_request()
    executor._process_one_request()

    assert executor.lanes.held("sess") is None and not executor.lanes.pending()
    answered = [call[0] for call in client.queue_response.call_args_list]
    assert [req_id for req_id, _ in answered] == ["req-1", "req-2"]
    for _, payload in answered:
        assert payload["success"] is False and payload["error_type"] == "render_in_progress"
        assert payload["render_kind"] == "scene_video" and "Nothing was executed" in payload["error"]


def test_a_script_proceeds_when_no_render_is_running(executor, monkeypatch):
    client = _fake_client(monkeypatch)
    _stub_session_path(monkeypatch, active=True)
    _render(monkeypatch, None)
    # Stop right after the gate: a routing error proves the script got past it.
    monkeypatch.setattr(executor, "route_request", lambda *a: (None, False, "routed past the gate"))
    _queue(executor)

    executor._process_one_request()

    req_id, payload = client.queue_response.call_args[0]
    assert req_id == "req-1" and payload["error"] == "routed past the gate"


def test_read_only_tools_run_during_a_render(monkeypatch):
    gate = _render(monkeypatch, "scene_video")
    for tool in ("list_moodboard_images", "inspect_moodboard_image",
                 "render_scene_image", "render_scene_video", "_scene_digest",
                 "_wait_generation_poll", "_detect_views_poll", "_await_generation_image",
                 "poll_generation", "get_all_queue_status", "list_scene_meshes", "list_rules",
                 "get_paint_layer_stack", "get_paint_channels"):
        assert gate.refusal(tool) is None, tool
    for tool in ("execute_bpy_script", "render_viewport", "crop_moodboard_image", "unknown"):
        assert gate.refusal(tool)["error_type"] == "render_in_progress", tool


def test_the_executor_refuses_and_never_holds():
    """The 3.4.2 hold (park the head script, fail it after 20 s) stays gone;
    the gate is one immediate refusal after the stale-session net."""
    src = (CHAT_ROOT / "core/main_thread_executor.py").read_text()
    for token in ("render_job_running", "RENDER_WAIT_MAX_S", "_render_wait_started"):
        assert token not in src, f"{token}: a render must never HOLD scripts"
    gate_at = src.index("refuse_during_render(req)")
    assert src.index("_reject_stale_session(req)") < gate_at < src.index("route_request(")
    gate = (CHAT_ROOT / "core/render_gate.py").read_text()
    assert "hold" not in gate.split('"""', 2)[2].lower()


def test_render_probe_helper_is_gone():
    assert not (ROOT / "src/scripts/mixar/modules/common/utils/render_jobs.py").exists()


def test_final_render_operator_is_gone():
    """The backend's render_scene tool was deleted; nothing can invoke the
    fire-and-forget final render any more, so it does not exist."""
    assert not (CHAT_ROOT / "ui/operators/agent_final_render_ops.py").exists()
    for path in (
        CHAT_ROOT / "constants.py",
        CHAT_ROOT / "core/executor.py",
        CHAT_ROOT / "core/executor_handlers.py",
        CHAT_ROOT / "core/main_thread_executor.py",
    ):
        text = path.read_text()
        assert "agent_final_render" not in text, path
        assert "final_render_result" not in text, path


def test_contract_doc_exists_and_is_linked():
    """docs/render-job-contract.md is the write-up the code comments point at;
    it must exist, describe both retired guards and the held-open preview
    flow, and be reachable from the agent guides and the modules that
    implement the contract."""
    doc = ROOT / "docs/render-job-contract.md"
    assert doc.exists()
    text = doc.read_text()
    for needle in (
        "is_job_running",
        "use_lock_interface",
        "render_complete",
        "splat_render_camera",
        "tests/test_render_job_guard.py",
        "mixie_chat.agent_preview_render",
        "__deferred_preview__",
        "preview_deferral",
        "render_gate",
        "render_in_progress",
        "graph_tag_ids_for_visible_update",
    ):
        assert needle in text, needle
    assert "agent_final_render" not in text
    for path in (
        ".claude/rules/private-docs-map.md",
        "AGENTS.md",
        "docs/modules/agent-execution.md",
        "src/scripts/mixar/modules/space_mixie_chat/core/main_thread_executor.py",
        "src/scripts/mixar/modules/space_mixie_chat/core/preview_render.py",
        "src/scripts/mixar/modules/space_mixie_chat/core/render_gate.py",
    ):
        assert "docs/render-job-contract.md" in (ROOT / path).read_text(), path


# --------------------------------------------------------------------------
# preview_render: Lock Interface and Preferences are the user's, never forced
# --------------------------------------------------------------------------


def test_preview_never_writes_the_lock_or_preferences():
    src = PREVIEW.read_text()
    assert "use_lock_interface" not in src
    assert "preferences.addons" not in src
    assert "compute_device_type" not in src


def test_preview_start_has_no_synchronous_render_path():
    src = PREVIEW.read_text()
    assert src.count("bpy.ops.render.render(") == 1
    assert 'bpy.ops.render.render("INVOKE_DEFAULT", write_still=False)' in src
    assert "EXEC_DEFAULT" not in src


def test_preview_render_handlers_only_schedule_a_timer():
    """render_complete / render_cancel fire on the job thread: the handler
    bodies register a timer and touch nothing else."""
    src = PREVIEW.read_text()
    start = src.index("def _schedule(")
    end = src.index("def _before_load(")
    block = src[start:end]
    assert "bpy.app.timers.register" in block
    for forbidden in ("bpy.data", "view_layer", "save_render", "setattr("):
        assert forbidden not in block, forbidden


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
    assert "run_on_main_thread(reconnect)" in block
    assert "check_orphaned_turns()" in (CHAT_ROOT / "core/turn_events.py").read_text()
    assert "\n                    check_orphaned_turns()\n" not in block


def test_sidecar_instance_read_goes_through_the_main_thread():
    src = (ROOT / "src/scripts/mixar/modules/connector/core/sidecar.py").read_text()
    start = src.index("def _instance()")
    end = src.index("def _health()", start)
    block = src[start:end]
    assert "_run_on_main(_read)" in block
