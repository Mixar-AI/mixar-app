# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Transport loss must neither change the project nor retry a mutation."""

import pytest

from mixar.modules.mcp_bridge.core import connector
from mixar.modules.common.ui_control.core.input import keyboard_key


def test_closed_instance_does_not_rebind_to_another_project(monkeypatch):
    first = ({"instance_id": "first"}, {"instance_id": "first"})
    second = ({"instance_id": "second"}, {"instance_id": "second"})
    monkeypatch.setattr(connector, "instances", lambda: [first])
    client = connector.Connector()
    assert client.attach() == first
    monkeypatch.setattr(connector, "instances", lambda: [second])
    monkeypatch.setattr(connector, "request", lambda *a, **k: (_ for _ in ()).throw(OSError("closed")))
    with pytest.raises(RuntimeError, match="was closed"):
        client.attach()
    assert client.instance == "first"


def test_lost_action_response_is_not_retried(monkeypatch):
    client = connector.Connector()
    monkeypatch.setattr(client, "attach", lambda **_: ({}, {"session_id": "scene"}))
    calls = []

    def lost(*args, **kwargs):
        calls.append(args)
        raise OSError("response lost after dispatch")

    monkeypatch.setattr(connector, "request", lost)
    with pytest.raises(OSError):
        client.call("mixar_ui_act", {"action": "click"}, "identity")
    assert len(calls) == 1


def test_scene_change_does_not_silently_retarget_calls(monkeypatch):
    record = {"instance_id": "desktop"}
    monkeypatch.setattr(connector, "instances", lambda: [(record,
        {"instance_id": "desktop", "session_id": "original"})])
    client = connector.Connector()
    client.attach()
    headers_seen = []

    def transport(record, method, path, payload=None, headers=None, **kwargs):
        if path == "/health":
            return {"instance_id": "desktop", "session_id": "new-scene"}
        headers_seen.append(headers)
        return {"result": {"isError": True}}

    monkeypatch.setattr(connector, "request", transport)
    client.call("mixar_ui_act", {}, "identity")
    assert headers_seen[0]["X-Mixar-Session-Id"] == "original"


@pytest.mark.parametrize("key", ["TIMER", "MOUSEMOVE", "LEFTMOUSE", "WINDOW_DEACTIVATE", "EVT_DROP"])
def test_keyboard_action_excludes_internal_events(key):
    assert not keyboard_key(key)


@pytest.mark.parametrize("key", ["G", "TWO", "RET", "NUMPAD_PERIOD", "F3"])
def test_keyboard_action_accepts_native_modeling_keys(key):
    assert keyboard_key(key)
