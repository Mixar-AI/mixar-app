# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""MCP scene admission cannot overlap chat or survive revocation/transport loss."""

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
import uuid

import pytest

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    try:
        importlib.import_module(_dep)
    except ImportError:
        sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.mcp_bridge.core import lease, rpc
from mixar.modules.space_mixie_chat.constants import SessionState
from mixar.modules.space_mixie_chat.core.session import SessionManager


def scene(name="Scene", session_id=None):
    return SimpleNamespace(name=name, mixie_session_id=session_id or str(uuid.uuid4()),
        mixie_chat_state="IDLE", mixie_run_open=False, mixie_run_id="",
        mixie_chat_is_busy=False, mixie_chat_mode="ASK", mixie_chat_active_turn_mode="",
        mixie_chat_cat_activity="", mixie_chat_cat_activity_until="")


@pytest.fixture
def env(monkeypatch):
    SessionManager.reset()
    first, second = scene(), scene("Second")
    handlers = SimpleNamespace(load_pre=[], undo_pre=[], redo_pre=[], persistent=lambda f: f)
    bpy = SimpleNamespace(data=SimpleNamespace(scenes=[first, second]),
        context=SimpleNamespace(scene=first),
        app=SimpleNamespace(handlers=handlers, timers=MagicMock()))
    now = [1000.0]
    monkeypatch.setattr(lease, "_runtime", lambda: (bpy, SessionManager()))
    monkeypatch.setattr(lease, "_enabled", lambda: True)
    monkeypatch.setattr(lease.time, "monotonic", lambda: now[0])
    for key, value in (("_operations", {}), ("_cleanup", []), ("_retired", {}),
                       ("_state_generations", {}), ("_transport_generation", 0)):
        monkeypatch.setattr(lease, key, value)
    from mixar.modules.space_mixie_chat.core import cat_activity
    monkeypatch.setattr(cat_activity, "reset_for_state", lambda *a: None)
    monkeypatch.setitem(sys.modules, "mixar.modules.agent_panel.core.cards",
                        SimpleNamespace(clear_cards=lambda **kw: None))
    yield SimpleNamespace(bpy=bpy, first=first, second=second, now=now)
    SessionManager.reset()


def params(target=None, operation_id=None, **kwargs):
    return {"operation_id": operation_id or str(uuid.uuid4()),
            "session_id": target.mixie_session_id if target else "", **kwargs}


def context(p):
    return {"mcp_operation_id": p["operation_id"], "chat_session_id": p["session_id"]}


def test_acquires_idle_scene_marks_visible_busy_and_repeated_begin_does_not_extend(env):
    p = params(env.first, timeout_seconds=60)
    accepted = lease.begin_operation(p)
    assert accepted["success"] and accepted["session_id"] == env.first.mixie_session_id
    assert env.first.mixie_chat_state == "BUSY" and env.first.mixie_chat_is_busy
    assert env.first.mixie_chat_mode == "ASK" and env.first.mixie_chat_active_turn_mode == "AGENT"
    assert SessionManager.has_active_session(env.first.mixie_session_id)
    env.now[0] += 10
    assert lease.begin_operation(p)["expires_in_seconds"] == 50
    assert lease.end_operation(p) == {"success": True, "released": True}
    assert env.first.mixie_chat_state == "IDLE" and not env.first.mixie_chat_is_busy
    assert not SessionManager.has_active_session(env.first.mixie_session_id)
    assert lease.begin_operation(p)["error_type"] == "operation_expired"


def test_overlapping_calls_refused_only_on_the_owned_scene(env):
    p = params(env.first)
    assert lease.begin_operation(p)["success"]
    assert lease.begin_operation(params(env.first))["error_type"] == "scene_busy"
    assert lease.begin_operation(params(env.second))["success"]
    assert lease.end_operation(params(env.first))["error_type"] == "operation_conflict"
    assert lease.authorize_script(p["session_id"], context(p)) is None


@pytest.mark.parametrize("state,open_run", [("BUSY", False), ("AWAITING_INPUT", False),
    ("MODIFYING", False), ("OFFLINE", False), ("CONNECTING", False), ("IDLE", True)])
def test_chat_and_worker_runs_cannot_be_taken_over(env, state, open_run):
    env.first.mixie_chat_state, env.first.mixie_run_open = state, open_run
    assert lease.begin_operation(params(env.first))["error_type"] == "scene_busy"
    assert env.first.mixie_chat_state == state


def test_opt_in_and_unambiguous_scene_required(env, monkeypatch):
    monkeypatch.setattr(lease, "_enabled", lambda: False)
    assert lease.begin_operation(params(env.first))["error_type"] == "mcp_disabled"
    monkeypatch.setattr(lease, "_enabled", lambda: True)
    env.second.mixie_session_id = env.first.mixie_session_id
    assert lease.begin_operation(params(env.first))["error_type"] == "scene_unavailable"
    assert lease.begin_operation(params())["error_type"] == "scene_unavailable"
    env.bpy.data.scenes.pop()
    env.first.mixie_session_id = "agentlane:other"
    assert lease.begin_operation(params())["error_type"] == "scene_unavailable"


def test_current_scene_without_chat_gets_uuid_without_starting_a_backend_run(env):
    env.first.mixie_session_id = ""
    accepted = lease.begin_operation(params())
    assert accepted["success"] and uuid.UUID(accepted["session_id"])
    assert not env.first.mixie_run_open


@pytest.mark.parametrize("change", [{"operation_id": "bad"}, {"session_id": "agent:x"},
    {"timeout_seconds": 0}, {"timeout_seconds": 601}, {"timeout_seconds": True},
    {"timeout_seconds": 10.5}])
def test_invalid_parameters_never_activate_scene(env, change):
    p = params(env.first)
    p.update(change)
    assert lease.begin_operation(p)["error_type"] == "invalid_params"
    assert env.first.mixie_chat_state == "IDLE"


def test_script_requires_exact_operation_and_explicit_scene_at_both_gates(env):
    p = params(env.first)
    lease.begin_operation(p)
    sid = p["session_id"]
    for route, ctx in ((sid, None), (sid, {"chat_session_id": env.second.mixie_session_id}),
        (sid, {**context(p), "mcp_operation_id": str(uuid.uuid4())}),
        ("agent:instance", context(p)), (env.second.mixie_session_id, context(p))):
        assert lease.authorize_script(route, ctx)["error_type"] == "mcp_operation_expired"
    assert lease.authorize_script(sid, context(p)) is None
    assert lease.authorize_script(env.second.mixie_session_id, None) is None
    env.now[0] += 121
    assert lease.authorize_script(sid, context(p))["error_type"] == "mcp_operation_expired"
    lease.tick()
    assert env.first.mixie_chat_state == "IDLE"
    SessionManager.set_state(env.first, SessionState.BUSY)
    assert lease.authorize_script(sid, context(p))["error_type"] == "mcp_operation_expired"


def test_stale_end_cannot_release_a_new_operation(env):
    old = params(env.first)
    lease.begin_operation(old)
    lease.end_operation(old)
    new = params(env.first)
    lease.begin_operation(new)
    assert lease.end_operation(old)["error_type"] == "operation_conflict"
    assert env.first.mixie_chat_state == "BUSY"
    assert lease.authorize_script(new["session_id"], context(new)) is None


def test_user_stop_revokes_lease_and_delayed_end_preserves_new_chat(env):
    p = params(env.first)
    lease.begin_operation(p)
    SessionManager.set_state(env.first, SessionState.IDLE)
    SessionManager.set_state(env.first, SessionState.BUSY)
    assert lease.end_operation(p) == {"success": True, "released": False}
    assert env.first.mixie_chat_state == "BUSY"
    assert lease.authorize_script(p["session_id"], context(p))["error_type"] == "mcp_operation_expired"


def test_viewport_stays_locked_during_mcp_even_while_another_tab_has_a_v3_run(env, monkeypatch):
    from mixar.modules.common.agent_execution import document
    from mixar.modules.agent_viewport_lock.core.state_probe import is_agent_executing
    monkeypatch.setattr(document, "run_active", lambda: True)
    p = params(env.first)
    lease.begin_operation(p)
    assert is_agent_executing(env.first)
    lease.end_operation(p)
    assert not is_agent_executing(env.first)


def test_disconnect_fences_immediately_and_restores_on_main_thread(env):
    p = params(env.first)
    lease.begin_operation(p)
    generation = lease.transport_generation()
    lease.invalidate()
    assert lease.transport_generation() > generation
    assert lease.authorize_script(p["session_id"], context(p))["error_type"] == "mcp_operation_expired"
    assert env.first.mixie_chat_state == "BUSY"
    lease.tick()
    assert env.first.mixie_chat_state == "IDLE"


def test_delayed_disconnect_cleanup_cannot_clear_a_new_chat(env):
    lease.begin_operation(params(env.first))
    lease.invalidate()
    SessionManager.set_state(env.first, SessionState.IDLE)
    SessionManager.set_state(env.first, SessionState.BUSY)
    lease.tick()
    assert env.first.mixie_chat_state == "BUSY"


def test_old_socket_teardown_cannot_revoke_replacement_transport(env, monkeypatch):
    from mixar.modules.space_mixie_chat.core import jsonrpc_client
    current = object()
    monkeypatch.setattr(jsonrpc_client, "get_jsonrpc_client", lambda: current)
    p = params(env.first)
    lease.begin_operation(p)
    lease.invalidate_transport(object())
    assert lease.authorize_script(p["session_id"], context(p)) is None
    lease.invalidate_transport(current)
    assert lease.authorize_script(p["session_id"], context(p))["error_type"] == "mcp_operation_expired"


def test_hooks_persist_and_file_read_or_undo_revokes(env):
    env.bpy.app.timers.is_registered.return_value = False
    lease.register()
    lease.register()
    for name in ("load_pre", "undo_pre", "redo_pre"):
        assert getattr(env.bpy.app.handlers, name) == [lease._on_document_change]
    p = params(env.first)
    lease.begin_operation(p)
    env.bpy.app.handlers.load_pre[0](None)
    assert env.first.mixie_chat_state == "IDLE"
    assert lease.authorize_script(p["session_id"], context(p))["error_type"] == "mcp_operation_expired"
    lease.unregister()
    assert env.bpy.app.handlers.load_pre == env.bpy.app.handlers.undo_pre == []


def test_shutdown_invalidation_does_not_touch_freed_blender_data(env, monkeypatch):
    lease.begin_operation(params(env.first))
    def no_bpy():
        raise AssertionError("Blender data has been freed")
    monkeypatch.setattr(lease, "_runtime", no_bpy)
    lease.unregister(shutdown=True)
    assert not lease._operations


def test_rpc_acknowledges_same_id_after_main_thread_work(env):
    scheduled, replies = [], []
    client = SimpleNamespace(is_connected=True, queue_response=lambda rid, value: replies.append((rid, value)))
    p = params(env.first)
    rpc.handle_request(client, "mcp.begin_operation", p, "request-id", schedule=scheduled.append)
    assert env.first.mixie_chat_state == "IDLE" and not replies
    scheduled[0]()
    assert replies[0][0] == "request-id" and replies[0][1]["success"]
    assert env.first.mixie_chat_state == "BUSY"


def test_notification_and_disconnected_scheduled_rpc_cannot_acquire(env):
    scheduled = []
    client = SimpleNamespace(is_connected=True, queue_response=MagicMock())
    rpc.handle_request(client, "mcp.begin_operation", params(env.first), None, schedule=scheduled.append)
    assert not scheduled
    rpc.handle_request(client, "mcp.begin_operation", params(env.first), "old", schedule=scheduled.append)
    lease.invalidate()
    scheduled[0]()
    assert not lease._operations and env.first.mixie_chat_state == "IDLE"
    client.queue_response.assert_not_called()


def test_queued_request_is_fenced_before_execution_even_if_a_new_chat_is_active(env, monkeypatch):
    from mixar.modules.space_mixie_chat.core import main_thread_executor as executor
    from mixar.modules.space_mixie_chat.core import queue_processor
    from mixar.modules.common.agent_execution.request import ExecutionRequest
    from mixar.modules.common.agent_execution import pump
    p = params(env.first)
    lease.begin_operation(p)
    queued = ExecutionRequest("stale", "raise AssertionError('must not execute')", "mcp_test",
                              p["session_id"], context(p))
    lease.end_operation(p)
    SessionManager.set_state(env.first, SessionState.BUSY)
    monkeypatch.setattr(queue_processor, "drain_pending_events", lambda: None)
    monkeypatch.setattr(executor, "_execution_gate_until", 0)
    monkeypatch.setattr(executor.lanes, "pending", lambda: True)
    monkeypatch.setattr(executor.lanes, "take_next", lambda: (queued, pump.READY, p["session_id"]))
    monkeypatch.setattr(executor.lanes, "switch_to", lambda lane: None)
    monkeypatch.setattr(executor, "_stop_timer_if_idle", lambda: None)
    replies = []
    monkeypatch.setattr(executor, "_send_error_response", lambda *args: replies.append(args))
    executor._process_one_request()
    assert replies == [("stale", "MCP operation is missing, expired or belongs to another scene",
                        "mcp_operation_expired")]


def test_admission_uses_real_session_state_contract(monkeypatch):
    from mixar.modules.common.ui_control.core import ownership
    from mixar.modules.common.ui_control.constants import UIError
    from mixar.modules.common.render_coordinator import core as renders
    monkeypatch.setattr(renders, "busy", lambda: False)
    scene = SimpleNamespace(mixie_chat_state="idle", mixie_run_open=False)
    monkeypatch.setattr(ownership, "bpy", SimpleNamespace(context=SimpleNamespace(
        window_manager=SimpleNamespace(mixar_window_resizing=False))))
    monkeypatch.setattr(ownership.observe, "main_window", lambda: SimpleNamespace(scene=scene))
    ownership.available()
    scene.mixie_run_open = True
    with pytest.raises(UIError, match="active scene operation"):
        ownership.available()
