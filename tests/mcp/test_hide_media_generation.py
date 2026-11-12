# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The Claude plugin's launcher offers no AI image or video generation; everyone else is unchanged.

Anthropic's Software Directory Policy allows no AI image, video or audio
generation in a listed plugin, and wants a title on every tool. The plugin
starts the launcher with MIXAR_MCP_HIDE_MEDIA_GENERATION=1: every request it
sends Mixar's backend then carries ``params._meta["mixar/hide_media_generation"]``
(the backend decides what is media and leaves it out), its own instructions
drop generated videos, and offline it lists the media-free saved tool list.
Without the variable the requests are exactly today's. Titles are for everyone.
"""

import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

import pytest
from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mixar.modules.common.ui_control.core import schema
from mixar.modules.mcp_bridge.constants import HIDE_MEDIA_ENV, HIDE_MEDIA_META
from mixar.modules.mcp_bridge.core import connector, stdio_server, tool_snapshot
from mixar.modules.mcp_bridge.core.relay import RelayServer

FLAG = {HIDE_MEDIA_META: True}
TOOL = {"name": "execute_bpy_script", "description": "Run bpy.", "inputSchema": {"type": "object"}}
GENERATE = {"name": "enqueue_generation", "description": "Images, videos and 3D.", "inputSchema": {"type": "object"}}
PARAMS = {"name": "get_generation_params", "description": "Params.", "inputSchema": {"type": "object"}}
NO_MEDIA_GENERATE = {**GENERATE, "description": "3D only."}


# ------------------------------------------------- requests to the backend

@pytest.fixture
def backend(monkeypatch):
    """A real relay; ``forwarded`` is what it hands the backend, ``sent`` the
    exact bodies the launcher wrote."""
    context = {"instance_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4()),
               "scene_name": "Scene", "connected": True, "signed_in": True}
    forwarded, sent = [], []

    def forward(request, snapshot, headers):
        forwarded.append(request)
        method, params = request["method"], request.get("params") or {}
        result = ({"protocolVersion": "2025-11-25"} if method == "initialize" else
                  {"tools": [TOOL], **({} if params.get("cursor") else {"nextCursor": "2"})}
                  if method == "tools/list" else {"content": [], "isError": False})
        return 200, {"jsonrpc": "2.0", "id": request["id"], "result": result}

    real = connector.request

    def recording(record, method, path, payload=None, headers=None, timeout=10):
        if path == "/mcp":
            sent.append(json.dumps(payload, allow_nan=False))
        return real(record, method, path, payload, headers, timeout)

    monkeypatch.setattr(connector, "request", recording)
    server = RelayServer(lambda: dict(context), forward)
    server.start()
    try:
        yield forwarded, sent
    finally:
        server.stop()


def exercise():
    client = connector.Connector()
    call_id = str(uuid.uuid4())
    assert client.catalog() == [TOOL, TOOL]
    client.call("execute_bpy_script", {"code": "print(1)"}, call_id)
    return call_id


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", " 1", "1 ", "01"])
def test_without_the_plugin_the_backend_gets_exactly_todays_requests(backend, monkeypatch, value):
    if value is None:
        monkeypatch.delenv(HIDE_MEDIA_ENV, raising=False)
    else:
        monkeypatch.setenv(HIDE_MEDIA_ENV, value)
    forwarded, sent = backend
    call_id = exercise()
    today = [
        {"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "mixar-local-connector", "version": "1"}}},
        {"jsonrpc": "2.0", "id": "catalog", "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": "catalog", "method": "tools/list", "params": {"cursor": "2"}},
        {"jsonrpc": "2.0", "id": call_id, "method": "tools/call", "params": {
            "name": "execute_bpy_script", "arguments": {"code": "print(1)"},
            "_meta": {"mixar/request-id": call_id}}},
    ]
    assert sent == [json.dumps(message) for message in today]  # Byte for byte.
    assert forwarded == today


def test_the_plugin_marks_every_backend_request_and_the_relay_keeps_it(backend, monkeypatch):
    monkeypatch.setenv(HIDE_MEDIA_ENV, "1")
    forwarded, _ = backend
    call_id = exercise()
    assert [request["method"] for request in forwarded] == ["initialize", "tools/list", "tools/list", "tools/call"]
    assert all(request["params"]["_meta"][HIDE_MEDIA_META] is True for request in forwarded)
    assert forwarded[2]["params"] == {"cursor": "2", "_meta": FLAG}
    assert forwarded[3]["params"]["_meta"] == {"mixar/request-id": call_id, **FLAG}
    assert forwarded[3]["params"]["arguments"] == {"code": "print(1)"}


def test_the_variable_is_read_once_when_the_launcher_starts(monkeypatch):
    monkeypatch.setenv(HIDE_MEDIA_ENV, "1")
    client = connector.Connector()
    monkeypatch.delenv(HIDE_MEDIA_ENV)
    assert client.hide_media is True and connector.Connector().hide_media is False
    assert client.upstream({}) == {"_meta": FLAG}
    assert connector.Connector().upstream({"cursor": "2"}) == {"cursor": "2"}


# ------------------------------------------------- the launcher's own text

class Offline:
    """A Mixar that is not open: tools come from the saved list."""

    def __init__(self, hide_media, state="absent", tools=None):
        self.hide_media, self.state, self.live = hide_media, state, tools
        self.tasks, self.health, self.record, self.instance = set(), {}, None, None

    def readiness(self):
        return self.state, ""

    def catalog(self):
        return [dict(tool) for tool in self.live]

    def cancel(self, call_id=None):
        pass


def session(fake):
    async def main():
        async with Client(stdio_server.create_server(fake)) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            guide = (await client.read_resource("mixar://guide")).contents[0].text
            prompt = (await client.get_prompt("build-and-verify", {"goal": "a cube"})).messages[0].content.text
            return client.instructions, guide, prompt, tools
    return asyncio.run(main())


def calls(fake, *requests):
    """Each (tool, arguments) called once in one session; the results in order."""
    async def main():
        async with Client(stdio_server.create_server(fake)) as client:
            return [await client.call_tool(name, arguments) for name, arguments in requests]
    return asyncio.run(main())


def test_the_plugin_gets_instructions_without_generated_videos():
    flat = " ".join(stdio_server.GUIDE_NO_MEDIA.split())
    assert "Splat worlds (world_labs) only when the user wants one." in flat
    assert "videos" not in flat
    for kept in ("world_labs", "enqueue_generation", "render_scene_video", "mixar_guide", "mixar_scene_new"):
        assert kept in flat
    changed = [(old, new) for old, new in zip(stdio_server.GUIDE.splitlines(), stdio_server.GUIDE_NO_MEDIA.splitlines())
               if old != new]
    assert changed == [("   Splat worlds (world_labs) and videos only when the user wants one.",
                        "   Splat worlds (world_labs) only when the user wants one.")]
    instructions, guide, prompt, _ = session(Offline(hide_media=True))
    assert instructions == guide == stdio_server.GUIDE_NO_MEDIA
    assert stdio_server.GUIDE_NO_MEDIA in prompt
    instructions, guide, prompt, _ = session(Offline(hide_media=False))
    assert instructions == guide == stdio_server.GUIDE and stdio_server.GUIDE in prompt


def test_the_launcher_script_reads_the_variable_from_its_environment(tmp_path):
    """src/scripts/mixar/mcp.py started as an AI app starts it, the variable set or not."""
    async def instructions(extra):
        script = Path(__file__).resolve().parents[2] / "src/scripts/mixar/mcp.py"
        env = {**{k: v for k, v in os.environ.items() if k != HIDE_MEDIA_ENV},
               "MIXAR_MCP_DISCOVERY_DIR": str(tmp_path / "discovery"), **extra}
        params = StdioServerParameters(command=sys.executable, args=[str(script)], env=env)
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                return (await asyncio.wait_for(client.initialize(), 10)).instructions
    assert asyncio.run(instructions({HIDE_MEDIA_ENV: "1"})) == stdio_server.GUIDE_NO_MEDIA
    assert asyncio.run(instructions({})) == stdio_server.GUIDE


# ------------------------------------------------- offline tool lists

def names(fake):
    return set(session(fake)[3])


def test_offline_the_plugin_lists_the_media_free_saved_list():
    tool_snapshot.save([TOOL, GENERATE, PARAMS])
    tool_snapshot.save([TOOL, NO_MEDIA_GENERATE, PARAMS], no_media=True)
    tools = session(Offline(hide_media=True))[3]
    assert tools["enqueue_generation"].description == "3D only."
    assert session(Offline(hide_media=False))[3]["enqueue_generation"].description == GENERATE["description"]


def test_offline_without_a_media_free_list_the_plugin_lists_no_generation():
    """A list saved by an older Mixar has no media-free copy beside it."""
    tool_snapshot.save([TOOL, GENERATE, PARAMS])
    listed = names(Offline(hide_media=True))
    assert "execute_bpy_script" in listed and not {"enqueue_generation", "get_generation_params"} & listed
    assert {"enqueue_generation", "get_generation_params"} <= names(Offline(hide_media=False))
    assert tool_snapshot.load(no_media=True) == [TOOL]
    assert tool_snapshot.load() == [TOOL, GENERATE, PARAMS]


def test_the_plugins_live_list_never_replaces_everyone_elses_saved_list():
    tool_snapshot.save([TOOL, GENERATE])
    names(Offline(hide_media=True, state="ready", tools=[TOOL, NO_MEDIA_GENERATE]))
    assert tool_snapshot.load() == [TOOL, GENERATE]
    assert tool_snapshot.load(no_media=True) == [TOOL, NO_MEDIA_GENERATE]
    names(Offline(hide_media=False, state="ready", tools=[TOOL]))
    assert tool_snapshot.load() == [TOOL] and tool_snapshot.load(no_media=True) == [TOOL, NO_MEDIA_GENERATE]


# ------------------------------------------------- the interface cannot press Generate

class Recording(Offline):
    """A ready Mixar that records what reaches it."""

    def __init__(self, hide_media):
        super().__init__(hide_media, state="ready", tools=[TOOL])
        self.called = []

    def call(self, name, arguments, call_id):
        self.called.append(name)
        return {"content": [{"type": "text", "text": "{}"}], "structuredContent": {"result": {}}}


ACT = {"context": "c", "target": "t", "action": "click"}


def test_the_plugin_neither_lists_nor_runs_the_interface_tools_that_act():
    assert schema.UI_ACTIONS == {"mixar_ui_act"}  # Observe and wait only read the interface.
    plugin, everyone = names(Offline(hide_media=True)), names(Offline(hide_media=False))
    assert everyone - plugin == {"mixar_ui_act"}
    assert {"mixar_ui_context", "mixar_ui_observe", "mixar_ui_wait", "mixar_scene_new"} <= plugin
    fake = Recording(hide_media=True)
    act, catalog = calls(fake, ("mixar_ui_act", ACT), ("mixar_tool_catalog", {"domain": "ui"}))
    assert act.is_error and fake.called == []
    assert act.structured_content["result"]["error"] == stdio_server.NO_MEDIA_UI.format(name="mixar_ui_act")
    assert "mixar_ui_act" not in {entry["name"] for entry in catalog.structured_content["result"]["tools"]}


def test_without_the_plugin_the_interface_tools_are_unchanged():
    fake = Recording(hide_media=False)
    act, catalog = calls(fake, ("mixar_ui_act", ACT), ("mixar_tool_catalog", {"domain": "ui"}))
    assert not act.is_error and fake.called == ["mixar_ui_act"]
    assert "mixar_ui_act" in {entry["name"] for entry in catalog.structured_content["result"]["tools"]}


# ------------------------------------------------- an older Mixar fails closed

def test_the_installation_record_says_this_mixar_honours_the_variable(tmp_path):
    """The plugin starts only a launcher whose record lists the feature; every
    other key is unchanged, so older readers keep working."""
    from mixar.modules.mcp_bridge.core import installation
    installation.provision(tmp_path / "python", tmp_path / "mcp.py", tmp_path / "Mixar", enabled=True)
    text = (installation.directory() / "installation.json").read_text()
    assert json.loads(text) == {"version": 1, "python": str(tmp_path / "python"), "script": str(tmp_path / "mcp.py"),
                                "executable": str(tmp_path / "Mixar"), "enabled": True,
                                "features": ["hide_media_generation"]}
    assert '"hide_media_generation"' in text  # What the plugin's start script checks.
    assert installation.disabled() is False


# ------------------------------------------------- titles

#: Proper nouns the backend's titles keep capitalised (mixar-backend modules/mcp/catalog.py TITLES).
PROPER_NOUNS = ("AI", "Blender", "Mixar", "Moodboard", "PBR", "Python", "UV")


def test_every_local_tool_has_a_short_sentence_case_title_in_both_places():
    assert set(schema.TITLES) == set(schema.SCHEMAS)
    assert len(set(schema.TITLES.values())) == len(schema.TITLES)
    for tool in schema.tools():
        title = tool["title"]
        assert tool["annotations"]["title"] == title == schema.TITLES[tool["name"]]
        assert 0 < len(title) <= 40 and title[0].isupper() and not title.endswith(".")
        rest = " ".join(word for word in title[1:].split(" ") if word.split("'")[0] not in PROPER_NOUNS)
        assert rest == rest.lower(), title
    _, _, _, listed = session(Offline(hide_media=False))
    for name, title in schema.TITLES.items():
        assert listed[name].title == title and listed[name].annotations.title == title


def test_backend_tools_keep_the_backends_titles():
    tool_snapshot.save([TOOL, {**GENERATE, "title": "Generate a 3D model"}])
    listed = session(Offline(hide_media=False))[3]
    assert listed["execute_bpy_script"].title is None
    assert listed["enqueue_generation"].title == "Generate a 3D model"
