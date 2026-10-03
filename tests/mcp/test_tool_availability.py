# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The scene tools reach an MCP session whenever Mixar can serve them, and the agent
is told the real reason when it cannot.

An AI app lists tools once while it starts: a Mixar still starting, a second app
left open, or a server connection that comes up late must not leave the session
with only the local tools, and a status must never send the agent after a wrong
cause ("backend too old") or into workarounds.
"""

import asyncio
from types import SimpleNamespace

import pytest
from mcp import Client
from mcp.types import Implementation

from mixar.modules.common.ui_control.core import service
from mixar.modules.mcp_bridge.core import availability, connector, eligibility, stdio_server

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
    assert connector.Connector().readiness()[0] == "absent"
    monkeypatch.setattr(installation, "start_in_progress", lambda: True)  # Started by another AI app.
    assert connector.Connector().readiness()[0] == "starting"
    monkeypatch.setattr(installation, "start_app", lambda: True)
    assert connector.Connector().readiness()[0] == "starting"


# ------------------------------------------------- waiting and rechecking

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


def test_a_starting_mixar_is_waited_for_and_a_signed_out_one_is_not(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(availability.asyncio, "sleep", lambda delay: real_sleep(0))
    tools, state = asyncio.run(availability.fetch_tools(Fake(["starting", "starting", "ready"]), 30))
    assert state == "ready" and tools and tools[0]["name"] == "execute_bpy_script"
    fake = Fake(["signed_out", "ready"])
    tools, state = asyncio.run(availability.fetch_tools(fake, 30))
    assert tools is None and state == "signed_out" and fake.catalog_calls == 0


@pytest.mark.parametrize("first_delay", [0.01, 30], ids=["timed_recheck", "context_wakes_recheck"])
def test_a_late_mixar_reaches_the_session_and_the_client_is_told_to_reload(monkeypatch, first_delay):
    monkeypatch.setattr(availability, "STARTUP_WAIT_SECONDS", 0)
    monkeypatch.setattr(availability, "RECHECK_FIRST_SECONDS", first_delay)
    fake = Fake(["signed_out", "signed_out", "ready"])

    async def main():
        changed = asyncio.Event()

        async def on_message(message):
            if getattr(message, "method", "") == "notifications/tools/list_changed":
                changed.set()

        # The initialize handshake, as Claude Code and Codex connect today.
        info = Implementation(name="claude-code", version="1")
        async with Client(stdio_server.create_server(fake), client_info=info, message_handler=on_message,
                          mode="legacy") as client:
            first = {tool.name for tool in (await client.list_tools()).tools}
            context = (await client.call_tool("mixar_ui_context", {})).structured_content["result"]
            await asyncio.wait_for(changed.wait(), 5)
            second = {tool.name for tool in (await client.list_tools()).tools}
            return first, context, second

    first, context, second = asyncio.run(main())
    assert "execute_bpy_script" not in first and "mixar_ui_context" in first
    assert context["scene_tools"] in {"signed_out", "loading"} and context["next_step"]
    assert "execute_bpy_script" in second


def test_interface_tools_stay_hidden_while_off_even_without_the_backend(monkeypatch):
    monkeypatch.setattr(availability, "STARTUP_WAIT_SECONDS", 0)
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
    ("ready", False, True, "loading"), ("signed_out", False, False, "signed_out"),
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
