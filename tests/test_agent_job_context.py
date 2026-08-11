# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent provenance capture for generation jobs."""

from dataclasses import dataclass, field
import sys
from types import SimpleNamespace

from mixar.modules.common.agent_execution_context import (
    clear_agent_execution_context,
    set_agent_execution_context,
)
from mixar.modules.common.job_queue.core.job import Job
from mixar.modules.space_mixie_chat.core.main_thread_executor import (
    _resolve_agent_context_ids,
)


@dataclass
class PayloadJob(Job):
    payload: dict = field(default_factory=dict)


def test_job_payload_is_stamped_only_during_agent_execution(monkeypatch):
    # Some standalone suites reinstall the bpy mock during collection, so use
    # the currently registered module rather than a collection-time reference.
    bpy = sys.modules["bpy"]
    monkeypatch.setattr(
        bpy.context,
        "window_manager",
        SimpleNamespace(mixie_instance_id="instance-123"),
        raising=False,
    )
    clear_agent_execution_context()

    try:
        set_agent_execution_context("session-123", "request-456")
        agent_job = PayloadJob(payload={"prompt": "oak bark"})
    finally:
        clear_agent_execution_context()

    assert agent_job.payload["agent_context"] == {
        "source": "agent",
        "session_id": "session-123",
        "turn_id": "request-456",
        "instance_id": "instance-123",
    }

    user_job = PayloadJob(payload={"prompt": "marble"})
    assert "agent_context" not in user_job.payload


def test_explicit_agent_ctx_values_are_used_for_job_stamp(monkeypatch):
    bpy = sys.modules["bpy"]
    monkeypatch.setattr(
        bpy.context,
        "window_manager",
        SimpleNamespace(mixie_instance_id="instance-explicit"),
        raising=False,
    )
    session_id, turn_id = _resolve_agent_context_ids(
        {"chat_session_id": "chat-session", "turn_id": "chat-turn"},
        "scene-routing-session",
        "transport-request",
    )

    try:
        set_agent_execution_context(session_id, turn_id)
        job = PayloadJob(payload={})
    finally:
        clear_agent_execution_context()

    assert job.payload["agent_context"] == {
        "source": "agent",
        "session_id": "chat-session",
        "turn_id": "chat-turn",
        "instance_id": "instance-explicit",
    }


def test_absent_agent_ctx_falls_back_for_job_stamp(monkeypatch):
    bpy = sys.modules["bpy"]
    monkeypatch.setattr(
        bpy.context,
        "window_manager",
        SimpleNamespace(mixie_instance_id="instance-fallback"),
        raising=False,
    )
    session_id, turn_id = _resolve_agent_context_ids(
        None, "scene-routing-session", "transport-request"
    )

    try:
        set_agent_execution_context(session_id, turn_id)
        job = PayloadJob(payload={})
    finally:
        clear_agent_execution_context()

    assert job.payload["agent_context"] == {
        "source": "agent",
        "session_id": "scene-routing-session",
        "turn_id": "transport-request",
        "instance_id": "instance-fallback",
    }


def test_matgen_forwards_context_captured_at_construction(monkeypatch):
    from mixar.modules.paint.procedural_materials import matgen_queue

    bpy = sys.modules["bpy"]
    monkeypatch.setattr(
        bpy.context,
        "window_manager",
        SimpleNamespace(mixie_instance_id="instance-matgen"),
        raising=False,
    )
    submitted = {}

    class Service:
        @staticmethod
        def enqueue(**kwargs):
            submitted.update(kwargs)

    monkeypatch.setattr(matgen_queue, "get_job_queue_service", lambda: Service())
    try:
        set_agent_execution_context("session-matgen", "request-matgen")
        job = matgen_queue.MatGenJob(prompt="weathered copper", pipeline="fast")
    finally:
        clear_agent_execution_context()

    job.submit(None, None)
    assert submitted["payload"]["agent_context"] == {
        "source": "agent",
        "session_id": "session-matgen",
        "turn_id": "request-matgen",
        "instance_id": "instance-matgen",
    }
