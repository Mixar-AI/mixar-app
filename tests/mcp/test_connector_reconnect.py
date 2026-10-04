# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A connection follows its scene into a reopened Mixar, and nowhere else on its own.

Instance ids are new on every launch, but a saved scene keeps its session id. So
when the bound app closes, the connection re-attaches only to the one running app
that has the same scene; otherwise it says how to choose an app explicitly.
"""

import pytest

from mixar.modules.mcp_bridge.core import connector

OLD = {"instance_id": "old", "port": 1, "token": "t"}
NEW = {"instance_id": "new", "port": 2, "token": "t"}


@pytest.fixture
def desktop(monkeypatch):
    state = {"live": [], "tabs": {}}

    def request(record, method, path, payload=None, headers=None, timeout=10):
        alive = {r["instance_id"]: h for r, h in state["live"]}
        if record["instance_id"] not in alive:
            raise OSError("connection refused")
        if path == "/health":
            return alive[record["instance_id"]]
        tabs = state["tabs"].get(record["instance_id"], [])
        return {"result": {"structuredContent": {"result": {"scenes": [{"session": s} for s in tabs]}}}}

    monkeypatch.setattr(connector, "request", request)
    monkeypatch.setattr(connector, "instances", lambda: list(state["live"]))
    return state


def bound(desktop):
    client = connector.Connector()
    desktop["live"] = [(OLD, {"instance_id": "old", "session_id": "scene-a", "scene_name": "Garden"})]
    client.attach()
    assert client.instance == "old" and client.bound_session == "scene-a"
    return client


def test_reopened_saved_scene_reattaches_to_the_new_app(desktop):
    client = bound(desktop)
    desktop["live"] = [(NEW, {"instance_id": "new", "session_id": "scene-b", "scene_name": "Other tab"})]
    desktop["tabs"]["new"] = ["scene-b", "scene-a"]
    record, _ = client.attach()
    assert record["instance_id"] == "new" and client.instance == "new"
    assert client.bound_session == "scene-a"


def test_another_document_is_never_chosen_silently(desktop):
    client = bound(desktop)
    desktop["live"] = [(NEW, {"instance_id": "new", "session_id": "scene-z", "scene_name": "Untitled"})]
    desktop["tabs"]["new"] = ["scene-z"]
    with pytest.raises(RuntimeError) as closed:
        client.attach()
    message = str(closed.value)
    assert "was closed" in message and "instance new" in message and "mixar_ui_context" in message
    assert client.instance == "old"


def test_the_scene_open_in_two_apps_is_ambiguous(desktop):
    client = bound(desktop)
    other = {"instance_id": "other", "port": 3, "token": "t"}
    desktop["live"] = [(NEW, {"instance_id": "new", "session_id": "scene-a"}),
                       (other, {"instance_id": "other", "session_id": "scene-a"})]
    with pytest.raises(RuntimeError, match="was closed"):
        client.attach()


def test_no_app_running_still_reports_unavailable(desktop):
    client = bound(desktop)
    desktop["live"] = []
    with pytest.raises(RuntimeError, match="starting or unavailable"):
        client.attach()


def test_input_release_before_a_scene_tool_is_not_pinned_to_a_scene(monkeypatch):
    sent = []

    def request(record, method, path, payload=None, headers=None, timeout=10):
        sent.append((path, payload["params"]["name"], headers.get("X-Mixar-Session-Id")))
        return {"result": {"isError": False, "content": [], "structuredContent": {"result": {}}}}

    monkeypatch.setattr(connector, "request", request)
    client = connector.Connector()
    client.bound_session = "stale-scene"
    monkeypatch.setattr(client, "attach", lambda **_: ({"instance_id": "a"}, {"ui_contract": "mixar_ui_v1"}))
    client.call("scene_overview", {}, "11111111-1111-1111-1111-111111111111")
    assert sent[0] == ("/ui", "mixar_ui_context", "")
    assert sent[1] == ("/mcp", "scene_overview", "stale-scene")


@pytest.mark.parametrize("name", ["mixar_project_open", "mixar_scene_new", "mixar_scene_switch"])
def test_scene_and_project_tools_release_the_connections_own_input_first(monkeypatch, name):
    sent = []

    def request(record, method, path, payload=None, headers=None, timeout=10):
        sent.append((path, payload["params"]["name"]))
        return {"result": {"isError": False, "content": [{"type": "text", "text": ""}],
                           "structuredContent": {"result": {}}}}

    monkeypatch.setattr(connector, "request", request)
    client = connector.Connector()
    monkeypatch.setattr(client, "attach", lambda **_: ({"instance_id": "a"}, {"ui_contract": "mixar_ui_v1"}))
    client.call(name, {}, "11111111-1111-1111-1111-111111111111")
    assert sent == [("/ui", "mixar_ui_context"), ("/ui", name)]
    sent.clear()
    client.call("mixar_ui_act", {}, "22222222-2222-2222-2222-222222222222")
    assert sent == [("/ui", "mixar_ui_act")]  # Interface input keeps its own lease.


def test_the_ai_app_travels_with_each_call_for_usage_attribution(monkeypatch):
    sent = []

    def request(record, method, path, payload=None, headers=None, timeout=10):
        sent.append(payload["params"]["_meta"])
        return {"result": {"isError": False, "content": [], "structuredContent": {"result": {}}}}

    monkeypatch.setattr(connector, "request", request)
    client = connector.Connector()
    monkeypatch.setattr(client, "attach", lambda **_: ({"instance_id": "a"}, {}))
    client.call("scene_overview", {}, "11111111-1111-1111-1111-111111111111")
    client.client = {"name": "codex-mcp-client", "version": "0.160.0"}
    client.call("scene_overview", {}, "22222222-2222-2222-2222-222222222222")
    assert "mixar/client" not in sent[0]
    assert sent[1] == {"mixar/request-id": "22222222-2222-2222-2222-222222222222",
                       "mixar/client": {"name": "codex-mcp-client", "version": "0.160.0"}}


@pytest.mark.parametrize("error_type,blocks", [("modal_active", True), ("not_ready", False)])
def test_only_an_unfinished_ui_operation_blocks_scene_tools(monkeypatch, error_type, blocks):
    sent = []

    def request(record, method, path, payload=None, headers=None, timeout=10):
        sent.append(path)
        if path == "/ui":
            return {"result": {"isError": True, "structuredContent": {"result": {
                "error_type": error_type, "error": "Finish or cancel the current UI operation before running a scene tool"}}}}
        return {"result": {"isError": False, "content": [], "structuredContent": {"result": {}}}}

    monkeypatch.setattr(connector, "request", request)
    client = connector.Connector()
    monkeypatch.setattr(client, "attach", lambda **_: ({"instance_id": "a"}, {"ui_contract": "mixar_ui_v1"}))
    if blocks:
        with pytest.raises(RuntimeError, match="Finish or cancel the current UI operation"):
            client.call("scene_overview", {}, "11111111-1111-1111-1111-111111111111")
        assert sent == ["/ui"]
    else:  # The controller is still starting after launch: nothing to release.
        client.call("scene_overview", {}, "11111111-1111-1111-1111-111111111111")
        assert sent == ["/ui", "/mcp"]
