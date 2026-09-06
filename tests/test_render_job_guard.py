# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A running render never blocks the agent.

The agent's final render is fire-and-forget on Blender's job thread and the
render evaluates its OWN depsgraph, so the agent keeps running scripts and the
user keeps working while it goes — exactly what a user's F12 does with Lock
Interface off. 3.4.2 briefly HELD every sandbox script while a RENDER job was
alive (then failed it after 20 s) and forced ``render.use_lock_interface`` on,
which froze every UI handler for the whole render. Both are gone and pinned
absent here; the thread-marshalling fixes from the same audit stay.
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


def _stub_session_path(monkeypatch, active=False):
    """Stop the request right after the (removed) render gate: the stale-session
    drop is the cheapest proof the script left the queue head and proceeded."""
    session_mod = ModuleType("mixar.modules.space_mixie_chat.core.session")
    session = MagicMock()
    session.has_active_session.return_value = active
    session_mod.get_session_manager = lambda: session
    monkeypatch.setitem(sys.modules, session_mod.__name__, session_mod)
    sweep = ModuleType("mixar.modules.space_mixie_chat.core.lane_scene_sweep")
    sweep.schedule_lane_scene_sweep = lambda: None
    monkeypatch.setitem(sys.modules, sweep.__name__, sweep)


def test_script_runs_while_a_render_job_is_alive(executor, monkeypatch):
    """bpy.app.is_job_running('RENDER') is True for the whole render; the
    head-of-queue script must still proceed on the very first tick."""
    client = _fake_client(monkeypatch)
    executor.bpy.app.is_job_running.return_value = True
    _stub_session_path(monkeypatch, active=False)
    _queue(executor)

    executor._process_one_request()

    # Left the queue head and went down the normal path (dropped by the
    # stale-session net, which answers the request) — never parked.
    assert executor._held is None
    client.queue_response.assert_called_once()
    req_id, _payload = client.queue_response.call_args[0]
    assert req_id == "req-1"


def test_executor_never_consults_the_render_job_state():
    src = (CHAT_ROOT / "core/main_thread_executor.py").read_text()
    for token in (
        "is_job_running",
        "render_job_running",
        "RENDER_WAIT_MAX_S",
        "RENDER_IN_PROGRESS_ERROR",
        "_render_wait_started",
    ):
        assert token not in src, f"{token}: a render must never gate scripts"


def test_render_probe_helper_is_gone():
    assert not (ROOT / "src/scripts/mixar/modules/common/utils/render_jobs.py").exists()


# --------------------------------------------------------------------------
# agent_final_render_ops: Lock Interface is the user's, never forced
# --------------------------------------------------------------------------


def _ops_module():
    for dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
        sys.modules.setdefault(dep, MagicMock(name=dep))
    from mixar.modules.space_mixie_chat.ui.operators import agent_final_render_ops

    return agent_final_render_ops


class _Render:
    """Attribute writes are recorded so a stray lock write is visible."""

    def __init__(self, lock):
        object.__setattr__(self, "writes", [])
        self.engine = "BLENDER_EEVEE_NEXT"
        self.resolution_percentage = 100
        self.filepath = "/tmp/x"
        self.image_settings = MagicMock()
        self.image_settings.file_format = "PNG"
        self.use_lock_interface = lock
        object.__setattr__(self, "writes", [])

    def __setattr__(self, name, value):
        self.writes.append(name)
        object.__setattr__(self, name, value)


def _scene(lock=False):
    scene = MagicMock()
    scene.render = _Render(lock)
    scene.world = None
    return scene


@pytest.mark.parametrize("lock", [False, True])
def test_final_render_leaves_lock_interface_alone(monkeypatch, lock):
    ops = _ops_module()
    fake_bpy = MagicMock(name="bpy")
    fake_bpy.data.lights = []
    fake_bpy.data.materials = []
    monkeypatch.setattr(ops, "bpy", fake_bpy)
    monkeypatch.setattr(ops, "_resolve_engine", lambda engine: None)

    scene = _scene(lock=lock)
    saved, _note, _orig, _capped = ops._apply_settings(
        scene, "current", 0, 0, "current", "/tmp/out.png"
    )
    assert scene.render.use_lock_interface is lock
    assert "lock" not in saved
    assert "use_lock_interface" not in scene.render.writes

    ops._restore_settings(scene, saved)
    assert scene.render.use_lock_interface is lock
    assert "use_lock_interface" not in scene.render.writes


def test_restore_ignores_a_3_4_2_saved_dict_with_a_lock_key():
    """A job dict persisted by the 3.4.2 operator still restores cleanly and
    does not resurrect the lock write."""
    ops = _ops_module()
    scene = _scene(lock=False)
    ops._restore_settings(
        scene, {"engine": "CYCLES", "rp": 50, "fp": "/tmp/a", "ff": "PNG", "lock": True}
    )
    assert scene.render.use_lock_interface is False
    assert "use_lock_interface" not in scene.render.writes


def test_final_render_operator_never_writes_the_lock():
    src = (CHAT_ROOT / "ui/operators/agent_final_render_ops.py").read_text()
    assert "use_lock_interface =" not in src


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
