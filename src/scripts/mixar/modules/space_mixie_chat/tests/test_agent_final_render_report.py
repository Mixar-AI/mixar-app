# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Final-render outcome reporting back to the backend.

The agent's render_scene tool is fire-and-forget: its turn ends when the
background render STARTS, so the client is the only witness of the outcome.
These tests pin the ``render.final_render_result`` notification contract:
the job_key echo, the sanitization (a local render path must never be sent),
and best-effort degradation (no client / pre-reporting job => no send, no
crash).
"""

import importlib
import os
import sys
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.constants import JSONRPCMethod  # noqa: E402
from mixar.modules.space_mixie_chat.ui.operators import (  # noqa: E402
    agent_final_render_ops,
)

JOB = {
    "job_key": "fr|sess-1|turn-9|1727000000000",
    "engine": "CYCLES",
    "started_at": 1000.0,
    "path": "/tmp/mixar_render_scene_secret.png",  # local — must not travel
}


def _client():
    client = MagicMock()
    client.send_notification.return_value = True
    return client


@pytest.fixture
def ws_client(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        agent_final_render_ops,
        "_get_ws_client",
        lambda: client,
    )
    return client


def test_done_report_echoes_job_key_without_local_paths(ws_client):
    agent_final_render_ops._report_result(
        JOB, "done", moodboard_name="Render 2026-09-01", duration_seconds=42.44
    )
    method, payload = ws_client.send_notification.call_args.args
    assert method == JSONRPCMethod.RENDER_FINAL_RESULT
    assert payload["job_key"] == JOB["job_key"]
    assert payload["status"] == "done"
    assert payload["engine"] == "CYCLES"
    assert payload["duration_seconds"] == 42.4
    assert payload["moodboard_image_name"] == "Render 2026-09-01"
    # The local temp render path never leaves the machine.
    assert "/tmp/" not in str(payload)
    assert "path" not in payload


def test_error_and_cancelled_reports(ws_client):
    agent_final_render_ops._report_result(
        JOB, "error", error="render produced no Render Result to save"
    )
    _, payload = ws_client.send_notification.call_args.args
    assert payload["status"] == "error"
    assert "no Render Result" in payload["error"]

    agent_final_render_ops._report_result(JOB, "cancelled", duration_seconds=5.0)
    _, payload = ws_client.send_notification.call_args.args
    assert payload["status"] == "cancelled"
    assert "error" not in payload


def test_lost_report_from_stale_self_heal(ws_client):
    agent_final_render_ops._report_result(
        JOB, "lost", error="render completion was lost"
    )
    _, payload = ws_client.send_notification.call_args.args
    assert payload["status"] == "lost"
    assert payload["job_key"] == JOB["job_key"]


def test_no_client_is_silent_noop(monkeypatch):
    monkeypatch.setattr(
        agent_final_render_ops, "_get_ws_client", lambda: None
    )
    # Must not raise.
    agent_final_render_ops._report_result(JOB, "done")


def test_pre_reporting_job_is_skipped(ws_client):
    """A job dict without job_key predates reporting — nothing to echo."""
    agent_final_render_ops._report_result({"path": "/tmp/x.png"}, "done")
    ws_client.send_notification.assert_not_called()


def test_send_failure_never_raises(ws_client):
    ws_client.send_notification.side_effect = RuntimeError("socket closed")
    # Must not raise — reporting is best-effort.
    agent_final_render_ops._report_result(JOB, "done")
