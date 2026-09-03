# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Behavioral regressions for lossless SSE handoff to Blender's main thread."""

import __future__
import importlib.util
import json
import queue
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src/scripts/mixar/modules/space_mixie_chat/core"


def _module(monkeypatch, name: str, **attributes):
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _package(monkeypatch, name: str):
    module = _module(monkeypatch, name)
    module.__path__ = []
    return module


def _install_logger_stub(monkeypatch):
    _package(monkeypatch, "mixar")
    _package(monkeypatch, "mixar.config")
    _module(
        monkeypatch,
        "mixar.config.logging_config",
        get_logger=lambda _name: MagicMock(),
    )


def _load_from_path(monkeypatch, name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    # Blender's test stubs can replace built-in-looking annotation names with
    # bpy-generated classes. Postponing annotations keeps this loader focused
    # on the runtime behavior under test, matching Blender's tolerant importer.
    code = compile(
        path.read_text(encoding="utf-8"),
        str(path),
        "exec",
        flags=__future__.annotations.compiler_flag,
        dont_inherit=True,
    )
    exec(code, module.__dict__)
    return module


def _load_sse_handler(monkeypatch):
    _install_logger_stub(monkeypatch)
    _package(monkeypatch, "sse_reliability")
    _package(monkeypatch, "sse_reliability.core")
    _module(
        monkeypatch,
        "sse_reliability.constants",
        AGENT_ATTACH_ENDPOINT="/attach",
        AGENT_CHAT_ENDPOINT="/chat",
        AGENT_INPUT_ENDPOINT="/input",
        ATTACH_RETRY_DELAYS=(0.0,),
        ATTACH_RETRY_MAX_SECONDS=1.0,
        SSE_CONNECT_RETRY_DELAYS=(0.0,),
        SSE_READ_TIMEOUT=1.0,
    )
    return _load_from_path(
        monkeypatch,
        "sse_reliability.core.sse_handler",
        CORE / "sse_handler.py",
    )


def _load_queue_processor(monkeypatch):
    _install_logger_stub(monkeypatch)
    _package(monkeypatch, "queue_reliability")
    _package(monkeypatch, "queue_reliability.core")
    _module(
        monkeypatch,
        "queue_reliability.constants",
        SessionState=SimpleNamespace(
            AWAITING_INPUT="AWAITING_INPUT",
            BUSY="BUSY",
            IDLE="IDLE",
            MODIFYING="MODIFYING",
        ),
        STREAMING_BATCH_LIMIT=10,
        TEMP_PLACEHOLDER_PREFIX="temp-",
        TIMER_INTERVAL=0.01,
        TIMER_INTERVAL_THROTTLED=0.03,
        TIMER_THROTTLE_CONTENT_THRESHOLD=1000,
    )
    _module(
        monkeypatch,
        "queue_reliability.core.session",
        get_session_manager=MagicMock,
    )
    _module(
        monkeypatch,
        "queue_reliability.core.slot_processor",
        SlotEventProcessor=object,
        get_slot_processor=MagicMock,
    )

    class FakeSSEEvent:
        def __init__(self, event_type: str, data=None):
            self.event_type = event_type
            self.data = data or {}

    _module(
        monkeypatch,
        "queue_reliability.core.sse_handler",
        SSEEvent=FakeSSEEvent,
    )
    _module(
        monkeypatch,
        "queue_reliability.core.message_helpers",
        add_agent_message=MagicMock(),
    )
    _module(
        monkeypatch,
        "queue_reliability.core.ui_utils",
        redraw_chat_areas=MagicMock(),
    )
    _module(
        monkeypatch,
        "bpy",
        app=SimpleNamespace(timers=MagicMock()),
        data=SimpleNamespace(scenes={}),
    )
    module = _load_from_path(
        monkeypatch,
        "queue_reliability.core.queue_processor",
        CORE / "queue_processor.py",
    )
    module._ensure_sse_timer_running = lambda: True
    return module


def _reset_queue(module, maxsize=1):
    module._sse_event_queue = queue.Queue(maxsize=maxsize)
    module._sse_queue_condition = threading.Condition()
    module._sse_queue_epoch = 0
    module._sse_scene_epochs = {}
    module._sse_drop_count = 0


def _wait_until_condition_has_waiter(condition, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with condition:
            if condition._waiters:
                return
        time.sleep(0.005)
    pytest.fail("producer did not begin waiting for queue capacity")


def test_rejected_event_does_not_advance_resume_cursor_and_becomes_lost(monkeypatch):
    module = _load_sse_handler(monkeypatch)
    handler = module.SSEStreamHandler(
        "https://example.invalid",
        on_event=lambda _event: False,
        on_error=lambda _error: None,
        on_complete=lambda: None,
    )
    handler._running.set()

    class Response:
        def iter_lines(self):
            yield f'data: {json.dumps({"seq": 7, "bubble_id": "bubble"})}'

    assert handler._consume_sse_stream(Response()) == "lost"
    assert handler._last_seq == -1


def test_none_callback_result_is_backward_compatible_acceptance(monkeypatch):
    module = _load_sse_handler(monkeypatch)
    received = []
    handler = module.SSEStreamHandler(
        "https://example.invalid",
        on_event=lambda event: received.append(event),
        on_error=lambda _error: None,
        on_complete=lambda: None,
    )

    handler._process_sse_line(
        f'data: {json.dumps({"seq": 8, "bubble_id": "bubble"})}'
    )

    assert len(received) == 1
    assert handler._last_seq == 8


def test_rejected_completion_becomes_lost_instead_of_silently_finishing(monkeypatch):
    module = _load_sse_handler(monkeypatch)
    handler = module.SSEStreamHandler(
        "https://example.invalid",
        on_event=lambda _event: True,
        on_error=lambda _error: None,
        on_complete=lambda: False,
    )
    handler._running.set()

    class Response:
        def iter_lines(self):
            yield "data: [DONE]"

    assert handler._consume_sse_stream(Response()) == "lost"


def test_normal_event_reports_rejection_after_bounded_backpressure(monkeypatch):
    module = _load_queue_processor(monkeypatch)
    _reset_queue(module)
    module._SSE_EVENT_ENQUEUE_TIMEOUT = 0.02
    module._sse_event_queue.put_nowait(("event", object(), "other"))

    accepted = module.queue_sse_event(module.SSEEvent("slot"), "scene")

    assert accepted is False
    assert module._sse_drop_count == 1


@pytest.mark.parametrize("terminal_kind", ["complete", "transport_error", "event_error"])
def test_terminal_items_wait_for_capacity_instead_of_dropping(
    monkeypatch, terminal_kind
):
    module = _load_queue_processor(monkeypatch)
    _reset_queue(module)
    first = ("event", object(), "other")
    module._sse_event_queue.put_nowait(first)
    result = {}

    def enqueue():
        if terminal_kind == "complete":
            result["accepted"] = module.queue_sse_complete("scene")
        elif terminal_kind == "transport_error":
            result["accepted"] = module.queue_sse_error("boom", "scene")
        else:
            result["accepted"] = module.queue_sse_event(
                module.SSEEvent("error"), "scene"
            )

    producer = threading.Thread(target=enqueue)
    producer.start()
    _wait_until_condition_has_waiter(module._sse_queue_condition)

    assert module._dequeue_sse_item_nowait() == first
    producer.join(timeout=1.0)

    assert not producer.is_alive()
    assert result["accepted"] is True
    queued = module._dequeue_sse_item_nowait()
    assert queued[2] == "scene"


def test_scene_cleanup_cancels_waiter_without_deadlock_and_preserves_other_order(
    monkeypatch,
):
    module = _load_queue_processor(monkeypatch)
    _reset_queue(module, maxsize=3)
    kept = [
        ("event", "first", "other-a"),
        ("event", "remove", "target"),
        ("event", "second", "other-b"),
    ]
    for item in kept:
        module._sse_event_queue.put_nowait(item)

    result = {}
    producer = threading.Thread(
        target=lambda: result.setdefault(
            "accepted", module.queue_sse_complete("target")
        )
    )
    producer.start()
    _wait_until_condition_has_waiter(module._sse_queue_condition)

    module.cleanup_sse_queue_for_scene("target")
    producer.join(timeout=1.0)

    assert not producer.is_alive()
    assert result["accepted"] is False
    assert list(module._sse_event_queue.queue) == [kept[0], kept[2]]


def test_timer_registration_failure_rejects_before_cursor_can_advance(monkeypatch):
    module = _load_queue_processor(monkeypatch)
    _reset_queue(module)
    module._ensure_sse_timer_running = lambda: False

    assert module.queue_sse_event(module.SSEEvent("slot"), "scene") is False
    assert module._sse_event_queue.empty()


def test_timer_rearm_failure_retracts_unconsumed_event(monkeypatch):
    module = _load_queue_processor(monkeypatch)
    _reset_queue(module)
    timer_results = iter((True, False))
    module._ensure_sse_timer_running = lambda: next(timer_results)

    assert module.queue_sse_event(module.SSEEvent("slot"), "scene") is False
    assert module._sse_event_queue.empty()
