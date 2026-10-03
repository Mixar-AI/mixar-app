# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""MCP usage is attributable without content.

* Every job submit says who asked for it (``X-Mixar-Job-Origin``): the user, the
  in-app agent (its callback ref) or an external AI app over MCP (the backend's
  ``mixar_job_origin`` marker, consumed like the ref so it never leaks).
* The local interface tools report ``mcp.tool_called`` for the AI app's calls
  only, never for the connector's own housekeeping calls.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.api.services import job_queue_service as JQS
from mixar.modules.common.job_queue.core import queue_manager as QM
from mixar.modules.common.job_queue.core.job import Job
from mixar.modules.common.utils.agent_feedback import take_job_origin
from mixar.modules.mcp_bridge.core import local_ui, usage


class _WM(dict):
    windows = ()
    mixie_instance_id = ""


class _RecordingJob(Job):
    def submit(self, on_success, on_error):
        self.sent_origin = JQS._submit_origin.get()


def _queue_with(monkeypatch, **props):
    wm = _WM(props)
    monkeypatch.setattr(QM.bpy, "context", SimpleNamespace(window_manager=wm, scene=SimpleNamespace(name="Scene")),
                        raising=False)
    return QM.FeatureQueue("feat_origin_" + "_".join(props) or "user"), wm


@pytest.mark.parametrize("props,expected", [
    ({}, "user"),
    ({"mixar_agent_ref": json.dumps({"generation_id": "g1", "session_id": "s"})}, "mixar_agent"),
    ({"mixar_job_origin": "mcp"}, "mcp"),
])
def test_submit_records_who_asked(monkeypatch, props, expected):
    queue, wm = _queue_with(monkeypatch, **props)
    job = _RecordingJob(label="Origin " + expected)
    assert queue.submit(job) is True
    assert job.origin == expected and "mixar_job_origin" not in wm


def test_the_mcp_marker_is_read_once_and_only_as_mcp():
    wm = _WM(mixar_job_origin="mcp")
    context = SimpleNamespace(window_manager=wm)
    assert take_job_origin(context) == "mcp" and take_job_origin(context) == ""
    assert take_job_origin(SimpleNamespace(window_manager=_WM(mixar_job_origin="admin"))) == ""


def test_the_submit_carries_the_origin_header(monkeypatch):
    queue = QM.FeatureQueue("feat_origin_header")
    job = _RecordingJob(label="Header")
    job.origin = "mcp"
    queue._submit_job_attempt(job)
    assert job.sent_origin == "mcp" and JQS._submit_origin.get() == ""

    sent = {}
    monkeypatch.setattr(JQS, "_require_auth", lambda: None)
    service = JQS.JobQueueService.__new__(JQS.JobQueueService)
    service.post_async = lambda path, **kw: sent.update(kw) or "r"
    with JQS.submitting_as("mcp"):
        service.enqueue("image_gen", "m", {})
    assert sent["headers"] == {"X-Mixar-Job-Origin": "mcp"}
    sent.clear()
    service.enqueue("image_gen", "m", {})
    assert "headers" not in sent  # Nothing extra outside a submit.


@pytest.mark.parametrize("name,expected", [
    ("claude-code", "claude-code"), ("codex-mcp-client", "codex"), ("cursor-vscode", "cursor"), ("", "direct")])
def test_ai_app_names_match_the_backend(name, expected):
    assert usage.client_of({"mixar/client": {"name": name, "version": "1.0"}})[0] == expected


def test_only_the_ai_apps_local_calls_are_reported(monkeypatch):
    from mixar.modules.common.ui_control.core import service
    reported = []
    monkeypatch.setattr(usage, "report", lambda *args: reported.append(args[0]))
    monkeypatch.setattr(service, "submit", lambda *a, **k: service.envelope({}, a[3]))
    owner = "11111111-1111-1111-1111-111111111111"
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "mixar_scenes", "arguments": {},
        "_meta": {"mixar/request-id": "22222222-2222-2222-2222-222222222222", "mixar/client": {"name": "codex"}}}}
    release = {"jsonrpc": "2.0", "id": "release", "method": "tools/call", "params": {
        "name": "mixar_ui_context", "arguments": {"release": True}}}
    local_ui.dispatch(call, owner, "s")
    local_ui.dispatch(release, owner, "s")
    assert reported == ["mixar_scenes"]
