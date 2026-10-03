# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""A failed routing/UI tick must not lose a taken RPC or strand its successor."""

import importlib
from unittest.mock import MagicMock

import pytest

from test_preview_deferral import deferral, executor, _fake_client, _queue


@pytest.fixture
def live_executor(executor, monkeypatch):
    client = _fake_client(monkeypatch)
    gate = importlib.import_module("mixar.modules.space_mixie_chat.core.render_gate")
    monkeypatch.setattr(gate.render_slot, "native_render_kind", lambda: None)
    return executor, client


@pytest.mark.parametrize("failure", ["route", "execute", "history", "restore", "events"])
def test_failed_stage_answers_and_next_request_runs(live_executor, monkeypatch, failure):
    executor, client = live_executor
    execute = MagicMock(return_value={"success": True})
    monkeypatch.setattr(executor.pump, "execute_request", execute)
    if failure == "route":
        monkeypatch.setattr(executor, "route_request", MagicMock(side_effect=[
            RuntimeError("injected"), (None, False, None)]))
    elif failure == "execute":
        execute.side_effect = [RuntimeError("injected"), {"success": True}]
    elif failure == "history":
        monkeypatch.setattr(executor, "archive_history", MagicMock(side_effect=RuntimeError("injected")))
    elif failure == "restore":
        monkeypatch.setattr(executor, "restore_after", MagicMock(side_effect=RuntimeError("injected")))
    else:
        events = importlib.import_module("mixar.modules.space_mixie_chat.core.queue_processor")
        monkeypatch.setattr(events, "drain_pending_events", MagicMock(side_effect=RuntimeError("injected")))
    _queue(executor, "first")
    _queue(executor, "next")
    executor._process_one_request()
    assert executor.get_inflight_script() is None
    executor._process_one_request()
    assert executor.get_inflight_script() is None
    assert not executor.lanes.pending()
    replies = [call.args for call in client.queue_response.call_args_list]
    assert [rid for rid, _ in replies] == ["first", "next"]
    assert replies[1][1]["success"] is True
    if failure in {"route", "execute"}:
        assert replies[0][1]["success"] is False
        assert replies[0][1]["effects_uncertain"] is (failure == "execute")
    else:
        assert replies[0][1]["success"] is True


@pytest.mark.parametrize("failure", ["full", "prefetch", "timer", "shutdown"])
def test_receipt_failure_answers_without_running(live_executor, monkeypatch, failure):
    executor, client = live_executor
    monkeypatch.setattr(executor, "_timer_active", False)
    monkeypatch.setattr(executor, "_shutdown_requested", failure == "shutdown")
    monkeypatch.setattr(executor, "maybe_start_prefetch", lambda *a: None)
    if failure == "full":
        monkeypatch.setattr(executor.lanes, "MAX_QUEUED", 0)
    elif failure == "prefetch":
        monkeypatch.setattr(executor, "maybe_start_prefetch", MagicMock(side_effect=RuntimeError("injected")))
    elif failure == "timer":
        executor.bpy.app.timers.register.side_effect = RuntimeError("injected")
    executor.queue_script_request("x", "rejected", tool_name="example", session_id="sess")
    client.queue_response.assert_called_once()
    rid, result = client.queue_response.call_args.args
    assert rid == "rejected" and result["success"] is False
    assert result["error_type"] == {"full": "queue_full", "prefetch": "prefetch_failed",
                                    "timer": "executor_unavailable", "shutdown": "executor_shutdown"}[failure]
    assert not executor.lanes.pending()


def test_timer_exception_keeps_future_ticks_alive(live_executor, monkeypatch):
    executor, _client = live_executor
    monkeypatch.setattr(executor, "_timer_active", False)
    monkeypatch.setattr(executor, "_shutdown_requested", False)
    _queue(executor, "still-queued")
    monkeypatch.setattr(executor, "_process_one_request", MagicMock(side_effect=RuntimeError("injected")))
    executor._ensure_timer_running()
    callback = executor.bpy.app.timers.register.call_args.args[0]
    assert callback() == executor.TIMER_INTERVAL
    assert executor._timer_active is True
    executor.lanes.clear()
    assert callback() is None
    assert executor._timer_active is False


def test_global_reset_answers_each_queued_request(live_executor):
    executor, client = live_executor
    _queue(executor, "first")
    _queue(executor, "second")
    executor.cleanup()
    replies = [call.args for call in client.queue_response.call_args_list]
    assert [rid for rid, _ in replies] == ["first", "second"]
    assert all(result["error_type"] == "executor_reset" for _, result in replies)
    assert not executor.lanes.pending()


def test_failure_after_response_does_not_answer_twice(live_executor, monkeypatch):
    executor, client = live_executor
    original = executor._execute_dequeued_request
    monkeypatch.setattr(executor.pump, "execute_request", lambda *a, **kw: {"success": True})
    def dispatch(*args):
        original(*args)
        raise RuntimeError("failure after reply")
    monkeypatch.setattr(executor, "_execute_dequeued_request", dispatch)
    _queue(executor, "once")
    executor._process_one_request()
    client.queue_response.assert_called_once()
