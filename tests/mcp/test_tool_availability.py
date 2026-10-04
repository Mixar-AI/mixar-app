# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Every Mixar tool is listed the moment an AI app connects, and a call made before
Mixar is ready says why.

An AI app lists tools once, when it connects: a Mixar that is closed, starting,
signed out or offline must not leave the session with only the local tools (the
launcher serves the list the app saved while signed in), and a status must
never send the agent after a wrong cause ("backend too old") or into workarounds.
"""

import asyncio
from types import SimpleNamespace

import pytest
from mcp import Client
from mcp.types import Implementation

from mixar.modules.common.ui_control.core import service
from mixar.modules.mcp_bridge.core import availability, connector, eligibility, stdio_server, tool_snapshot

BACKEND_TOOL = {"name": "execute_bpy_script", "description": "Run bpy.", "inputSchema": {"type": "object"},
                "_meta": {"mixar/domain": "build"}}


# ---------------------------------------------------------------- app choice

def app(name, *, signed_in=True, connected=True):
    return ({"instance_id": name, "port": 1, "token": "t"},
            {"instance_id": name, "session_id": "s-" + name, "signed_in": signed_in, "connected": connected})


@pytest.fixture
def desktop(monkeypatch):
    live = []
    monkeypatch.setattr(connector, "instances", lambda: list(live))
    monkeypatch.setattr(connector, "request", lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))
    return live


def test_the_signed_in_app_is_chosen_when_another_is_open(desktop):
    desktop[:] = [app("old", signed_in=False, connected=False), app("new")]
    record, _ = connector.Connector().attach()
    assert record["instance_id"] == "new"


def test_two_usable_apps_still_need_a_choice(desktop):
    desktop[:] = [app("a"), app("b")]
    client = connector.Connector()
    assert client.readiness()[0] == "choose"
    with pytest.raises(RuntimeError, match="Several Mixar applications"):
        client.attach()


def test_readiness_names_what_the_user_must_do(desktop, monkeypatch):
    desktop[:] = [app("only", signed_in=False, connected=False)]
    assert connector.Connector().readiness()[0] == "signed_out"
    restoring = app("only", signed_in=False, connected=False)
    restoring[1]["signing_in"] = True
    desktop[:] = [restoring]
    assert connector.Connector().readiness()[0] == "starting"
    desktop[:] = [app("only")]
    assert connector.Connector().readiness()[0] == "ready"
    desktop[:] = []
    import mixar.modules.mcp_bridge.core.installation as installation
    monkeypatch.setattr(installation, "start_app", lambda: False)
    monkeypatch.setattr(installation, "start_in_progress", lambda: False)
    absent = connector.Connector()
    assert absent.readiness()[0] == "absent"
    assert absent.readiness()[0] == "absent"  # Not "starting" on the next attempt.
    monkeypatch.setattr(installation, "start_in_progress", lambda: True)  # Started by another AI app.
    assert connector.Connector().readiness()[0] == "starting"


def test_only_a_tool_call_opens_a_closed_mixar(desktop, monkeypatch):
    """AI apps list tools whenever a session starts; that must never launch
    Mixar. Asking for something in Mixar may."""
    import mixar.modules.mcp_bridge.core.installation as installation
    started = []
    monkeypatch.setattr(installation, "start_app", lambda: started.append(1) or True)
    monkeypatch.setattr(installation, "start_in_progress", lambda: bool(started))
    tool_snapshot.save([dict(BACKEND_TOOL)])
    client = connector.Connector()
    out = run_session(client)
    assert "execute_bpy_script" in out["tools"] and client.readiness()[0] == "absent" and not started
    with pytest.raises(RuntimeError, match="starting"):
        client.call("scene_overview", {}, "call-1")
    assert started == [1] and client.readiness()[0] == "starting"


# ------------------------------------------- every tool listed at once

class Fake:
    """A Mixar whose readiness steps through ``states``; the last one sticks."""

    def __init__(self, states):
        self.states, self.tasks, self.health = list(states), set(), {"connected": True}
        self.catalog_calls, self.record, self.instance = 0, {}, None

    def readiness(self):
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return state, ""

    def catalog(self):
        self.catalog_calls += 1
        return [dict(BACKEND_TOOL)]

    def attach(self):
        return {}, {"session_id": "s"}

    def call(self, name, arguments, call_id):
        payload = {"result": {"contract": "mixar_ui_v1", "ui_control": False}, "usage": {}}
        return {"content": [{"type": "text", "text": ""}], "structuredContent": payload, "isError": False}

    def cancel(self, call_id=None):
        pass


def run_session(fake, client_name="claude-code", steps=None):
    async def main():
        info = Implementation(name=client_name, version="1")
        async with Client(stdio_server.create_server(fake), client_info=info) as client:
            out = {"tools": {t.name for t in (await client.list_tools()).tools}}
            for name in steps or ():
                out[name] = (await client.call_tool(name, {})).structured_content
            return out
    return asyncio.run(main())


def test_a_ready_mixar_lists_live_tools_and_saves_them_for_later(monkeypatch):
    fake = Fake(["ready"])
    first = run_session(fake)
    assert "execute_bpy_script" in first["tools"] and fake.catalog_calls == 1
    assert tool_snapshot.load() == [BACKEND_TOOL]


@pytest.mark.parametrize("state", ["signed_out", "starting", "absent", "choose", "closed"])
def test_every_tool_is_listed_at_once_while_mixar_is_not_ready(state):
    tool_snapshot.save([dict(BACKEND_TOOL)])
    fake = Fake([state])
    out = run_session(fake, steps=["mixar_ui_context"])
    assert "execute_bpy_script" in out["tools"] and fake.catalog_calls == 0  # No waiting.
    status = out["mixar_ui_context"]["result"]
    assert status["scene_tools"] == state and status["next_step"]


def test_server_connection_down_lists_the_saved_tools_and_says_connecting():
    tool_snapshot.save([dict(BACKEND_TOOL)])
    fake = Fake(["ready"])
    fake.catalog = lambda: (_ for _ in ()).throw(OSError("backend unreachable"))
    fake.health = {"connected": False}
    out = run_session(fake, steps=["mixar_ui_context"])
    assert "execute_bpy_script" in out["tools"]
    assert out["mixar_ui_context"]["result"]["scene_tools"] == "connecting"


def test_without_a_saved_list_the_session_says_to_reconnect_once_mixar_is_ready():
    fake = Fake(["signed_out", "signed_out", "ready"])  # Never saved: first use, signed out.
    out = run_session(fake, steps=["mixar_ui_context", "mixar_ui_context"])
    assert "execute_bpy_script" not in out["tools"] and "mixar_ui_context" in out["tools"]
    status = out["mixar_ui_context"]["result"]
    assert status["scene_tools"] == "reconnect" and "/mcp" in status["next_step"]


def test_a_corrupt_saved_list_is_ignored():
    tool_snapshot.path().parent.mkdir(parents=True, exist_ok=True)
    tool_snapshot.path().write_text("{not json")
    assert tool_snapshot.load() is None
    tool_snapshot.path().write_text('{"version": 1, "tools": [{"description": "nameless"}]}')
    assert tool_snapshot.load() is None


def test_the_app_saves_the_list_once_signed_in_and_hourly(monkeypatch):
    tool_snapshot.forget()
    calls = []

    def forward(request, context, headers):
        calls.append(request["method"])
        if request["method"] == "initialize":
            return 200, {"result": {"protocolVersion": "2025-11-25"}}
        return 200, {"result": {"tools": [dict(BACKEND_TOOL)]}}

    ready = {"signed_in": True, "connected": True, "backend_url": "http://127.0.0.1:1",
             "headers": {}, "instance_id": "i", "session_id": "s"}
    assert not tool_snapshot.refresh_if_due({**ready, "signed_in": False}, forward, now=0)
    assert tool_snapshot.refresh_if_due(ready, forward, now=0)
    tool_snapshot._state["thread"].join(5)
    assert calls == ["initialize", "tools/list"] and tool_snapshot.load() == [BACKEND_TOOL]
    assert not tool_snapshot.refresh_if_due(ready, forward, now=60)  # Fresh enough.
    assert tool_snapshot.refresh_if_due(ready, forward, now=tool_snapshot.REFRESH_SECONDS + 1)
    tool_snapshot._state["thread"].join(5)
    tool_snapshot.forget()  # Signed out: the next sign-in saves again at once.
    assert tool_snapshot.refresh_if_due(ready, forward, now=tool_snapshot.REFRESH_SECONDS + 2)
    tool_snapshot._state["thread"].join(5)


def test_status_is_reported_while_the_interface_controller_starts(monkeypatch):
    fake = Fake(["ready"])

    def starting(name, arguments, call_id):
        payload = {"result": {"error_type": "not_ready", "error": "Mixar UI controller is starting"}, "usage": {}}
        return {"content": [{"type": "text", "text": ""}], "structuredContent": payload, "isError": True}
    fake.call = starting

    async def main():
        async with Client(stdio_server.create_server(fake)) as client:
            await client.list_tools()
            return (await client.call_tool("mixar_ui_context", {})).structured_content["result"]
    result = asyncio.run(main())
    assert result["error_type"] == "not_ready" and result["scene_tools"] == "available"


def test_interface_tools_stay_hidden_while_off_even_without_the_backend(monkeypatch):
    fake = Fake(["signed_out"])
    fake.health = {"ui_control": False}

    async def main():
        async with Client(stdio_server.create_server(fake)) as client:
            return {tool.name for tool in (await client.list_tools()).tools}
    names = asyncio.run(main())
    assert not {"mixar_ui_observe", "mixar_ui_act", "mixar_ui_wait"} & names
    assert {"mixar_ui_context", "mixar_scenes", "mixar_project_open"} <= names


# ------------------------------------------------------------ honest status

@pytest.mark.parametrize("state,listed,connected,expected", [
    ("ready", True, True, "available"), ("ready", True, False, "connecting"),
    ("ready", False, True, "reconnect"), ("ready", False, False, "connecting"),
    ("signed_out", False, False, "signed_out"),
    ("choose", False, True, "choose"), ("absent", False, False, "absent"),
])
def test_scene_tool_status(state, listed, connected, expected):
    status = availability.scene_tools(listed, state, {"connected": connected})
    assert status["scene_tools"] == expected
    assert bool(status["next_step"]) is (expected != "available")


def test_a_desktop_the_server_cannot_see_is_not_an_old_backend():
    unseen = SimpleNamespace(status_code=404, json=lambda: {
        "detail": "The selected Mixar desktop is unavailable for this account."})
    missing_route = SimpleNamespace(status_code=404, json=lambda: {"detail": "Not Found"})
    assert eligibility._not_found_reason(unseen) == "desktop_not_connected"
    assert eligibility._not_found_reason(missing_route) == "backend_update_required"


def test_interface_off_no_longer_claims_scene_tools_work():
    assert "still work" not in service.UI_CONTROL_OFF
    assert "mixar_ui_context" in service.UI_CONTROL_OFF


@pytest.mark.parametrize("logged_in,expired,expected", [(True, False, True), (True, True, False), (False, False, False)])
def test_context_reports_sign_in_without_raising(monkeypatch, logged_in, expired, expected):
    wm = SimpleNamespace(mixie_chat_is_logged_in=logged_in, mixie_chat_session_expired=expired)
    monkeypatch.setattr(service, "bpy", SimpleNamespace(context=SimpleNamespace(window_manager=wm)))
    assert service._is_signed_in() is expected


def test_a_failing_refresh_backs_off_up_to_hourly():
    """A backend without /api/v1/mcp must not be polled every 15 s forever."""
    import time
    tool_snapshot.forget()
    ok = {"value": False}

    def forward(request, context, headers):
        if not ok["value"]:
            return 404, {"detail": "Not Found"}
        if request["method"] == "initialize":
            return 200, {"result": {"protocolVersion": "2025-11-25"}}
        return 200, {"result": {"tools": [dict(BACKEND_TOOL)]}}

    ready = {"signed_in": True, "connected": True, "backend_url": "http://127.0.0.1:1"}
    waits = []
    for _ in range(9):
        now = time.monotonic()
        while not tool_snapshot.refresh_if_due(ready, forward, now=now):
            now += 1
        tool_snapshot._state["thread"].join(5)
        waits.append(tool_snapshot._state["saved_at"] + tool_snapshot.REFRESH_SECONDS - time.monotonic())
    assert [round(w / 15) * 15 for w in waits[:4]] == [15, 30, 60, 120]
    assert max(waits) <= tool_snapshot.REFRESH_SECONDS
    ok["value"] = True
    tool_snapshot.refresh_if_due(ready, forward, now=time.monotonic() + tool_snapshot.REFRESH_SECONDS)
    tool_snapshot._state["thread"].join(5)
    assert tool_snapshot._state["delay"] == tool_snapshot.RETRY_SECONDS  # Success resets it.
    tool_snapshot.forget()
