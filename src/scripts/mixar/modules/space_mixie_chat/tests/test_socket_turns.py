# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Socket-delivered turns of an open run (``agent.turn.*`` → the SSE queue).

Pins ``core/turn_events.py``: events are deduped by ``(turn_id, seq)``,
buffered until the scene is resolved on the main thread and flushed in
order, ``ended`` reuses the [DONE] finalisation with the run's reported
status, unknown sessions / turns are dropped, and a scene teardown stops
delivery. Companion of ``test_open_run.py``.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from _open_run_support import (  # noqa: F401 — fixtures are collected by name
    _scene,
    clean_state,
    live_bpy,
)
from mixar.modules.space_mixie_chat.constants import JSONRPCMethod  # noqa: E402
from mixar.modules.space_mixie_chat.core import queue_processor  # noqa: E402
from mixar.modules.space_mixie_chat.core import turn_events  # noqa: E402


@pytest.fixture
def socket_env(monkeypatch, live_bpy):
    """Capture what turn_events hands to the main thread and to the queue."""
    import mixar.modules.space_mixie_chat.core.main_thread_executor as mte

    main_thread = []
    monkeypatch.setattr(mte, "run_on_main_thread", lambda fn: main_thread.append(fn))
    queued = []
    monkeypatch.setattr(queue_processor, "queue_sse_event",
                        lambda ev, name: queued.append((name, ev.data)) or True)
    monkeypatch.setattr(queue_processor, "queue_sse_complete",
                        lambda name: queued.append((name, "[DONE]")) or True)
    begun = []
    monkeypatch.setattr(turn_events, "_begin_scene_turn",
                        lambda scene, run_id: begun.append((scene.name, run_id)))
    scene = _scene(session_id="sid-1")
    live_bpy.data.scenes.append(scene)
    return SimpleNamespace(main_thread=main_thread, queued=queued, begun=begun, scene=scene)


def _started(turn="t1", session="sid-1", run="r1"):
    turn_events.handle_turn_notification(
        JSONRPCMethod.AGENT_TURN_STARTED,
        {"session_id": session, "turn_id": turn, "run_id": run, "kind": "wakeup"},
    )


def _event(seq, turn="t1", payload=None):
    turn_events.handle_turn_notification(
        JSONRPCMethod.AGENT_TURN_EVENT,
        {"session_id": "sid-1", "turn_id": turn, "run_id": "r1", "seq": seq,
         "event": payload or {"bubble_id": "b1", "seq": seq, "content": {"append": str(seq)}}},
    )


def _ended(status, turn="t1"):
    turn_events.handle_turn_notification(
        JSONRPCMethod.AGENT_TURN_ENDED,
        {"session_id": "sid-1", "turn_id": turn, "run_id": "r1", "status": status},
    )


def _drain(env):
    while env.main_thread:
        env.main_thread.pop(0)()


def test_events_before_scene_resolution_are_buffered_in_order(socket_env):
    env = socket_env
    _started()
    _event(0)
    _event(1)
    assert env.queued == [], "nothing renders before the scene is known"

    _drain(env)
    assert env.begun == [("Scene", "r1")]
    assert [d["seq"] for _, d in env.queued] == [0, 1]
    assert all(name == "Scene" for name, _ in env.queued)

    _event(2)
    assert env.queued[-1][1]["seq"] == 2

    _ended("in_progress")
    assert env.queued[-2][1] == {"type": "run_status", "run_id": "r1", "status": "in_progress"}
    assert env.queued[-1][1] == "[DONE]"


def test_dedupe_by_turn_id_and_seq(socket_env):
    env = socket_env
    _started()
    _drain(env)
    _event(0)
    _event(0)  # replayed delivery
    _event(1)
    _event(1)
    assert [d["seq"] for _, d in env.queued] == [0, 1]

    # seq restarts per turn — the same seq on another turn is a new event.
    _started(turn="t2")
    _drain(env)
    _event(0, turn="t2")
    assert [d["seq"] for _, d in env.queued] == [0, 1, 0]


def test_ended_completed_closes_run_via_run_status(socket_env):
    env = socket_env
    _started()
    _drain(env)
    _ended("completed")
    assert env.queued[0][1]["status"] == "completed"
    assert env.queued[1][1] == "[DONE]"


def test_ended_before_resolution_is_flushed_after_open(socket_env):
    env = socket_env
    _started()
    _event(0)
    _ended("in_progress")
    assert env.queued == []
    _drain(env)
    assert [d if d == "[DONE]" else d.get("seq", d.get("type")) for _, d in env.queued] == [
        0, "run_status", "[DONE]"
    ]


def test_unknown_session_is_dropped(socket_env):
    env = socket_env
    _started(session="nope")
    _event(0)
    _drain(env)
    _event(1)
    _ended("completed")
    assert env.begun == []
    assert env.queued == []


def test_event_for_turn_never_started_is_dropped(socket_env):
    env = socket_env
    _event(0, turn="ghost")
    _ended("completed", turn="ghost")
    assert env.queued == []


def test_scene_teardown_stops_socket_delivery(socket_env):
    env = socket_env
    _started()
    _drain(env)
    _event(0)
    queue_processor.cleanup_sse_queue_for_scene("Scene")  # abort / New Chat / switch
    _event(1)
    _ended("in_progress")
    assert [d["seq"] for _, d in env.queued if d != "[DONE]" and "seq" in d] == [0]
    assert "[DONE]" not in [d for _, d in env.queued]


def test_begin_scene_turn_opens_run_and_goes_busy(monkeypatch, live_bpy):
    import mixar.modules.space_mixie_chat.core.executor as executor_mod
    import mixar.modules.space_mixie_chat.core.message_helpers as helpers
    import mixar.modules.space_mixie_chat.core.ui_utils as ui_utils

    executor = MagicMock()
    monkeypatch.setattr(executor_mod, "get_executor", lambda: executor)
    monkeypatch.setattr(helpers, "start_loader_animation", lambda: None)
    monkeypatch.setattr(ui_utils, "redraw_chat_areas", lambda: None)

    scene = _scene()
    stale = scene.mixie_chat_messages.add()
    stale.sender, stale.bubble_id, stale.loader_visible = 'AGENT', "temp_placeholder_old", True

    turn_events._begin_scene_turn(scene, "r9")

    assert scene.mixie_run_open and scene.mixie_run_id == "r9"
    assert scene.mixie_chat_state == "BUSY"
    executor.begin_agent_turn.assert_called_once()
    placeholders = [m for m in scene.mixie_chat_messages if m.bubble_id.startswith("temp_placeholder_")]
    assert len(placeholders) == 1 and placeholders[0] is not stale
    assert placeholders[0].loader_visible


def test_jsonrpc_client_dispatches_turn_notifications():
    from mixar.modules.space_mixie_chat.core.jsonrpc_client import JSONRPCWebSocketClient

    seen = []
    client = JSONRPCWebSocketClient(
        "http://x", "cid", on_turn_event=lambda m, p: seen.append((m, p))
    )
    for method in (JSONRPCMethod.AGENT_TURN_STARTED, JSONRPCMethod.AGENT_TURN_EVENT,
                   JSONRPCMethod.AGENT_TURN_ENDED):
        client._handle_message({"jsonrpc": "2.0", "method": method, "params": {"turn_id": "t"}})
    assert [m for m, _ in seen] == [
        "agent.turn.started", "agent.turn.event", "agent.turn.ended",
    ]


def test_interjection_started_turn_kind_user_opens_like_a_wakeup(socket_env):
    """Every backend-started turn reaches the socket — the one an interjection
    starts arrives as `kind: "user"` and is opened exactly like a wake-up."""
    env = socket_env
    turn_events.handle_turn_notification(
        JSONRPCMethod.AGENT_TURN_STARTED,
        {"session_id": "sid-1", "turn_id": "t-user", "run_id": "r1", "kind": "user"},
    )
    _event(0, turn="t-user")
    _drain(env)
    assert env.begun == [("Scene", "r1")]
    assert [d["seq"] for _, d in env.queued] == [0]
    _ended("in_progress", turn="t-user")
    assert env.queued[-1][1] == "[DONE]"
