# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The launcher passes the backend's discovery hints through and indexes its own UI tools."""

import asyncio
import json

from mcp import Client

from mixar.modules.mcp_bridge.core import stdio_server

BACKEND_TOOLS = [
    {"name": "execute_bpy_script", "description": "Run bpy.\nMixar credits: free.",
     "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}},
                     "additionalProperties": False},
     "_meta": {"mixar/domain": "build", "anthropic/alwaysLoad": True}},
    {"name": "mixar_tool_catalog", "description": "Index of Mixar tools.\nMixar credits: free.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "domain": {"enum": ["account", "build"]}},
         "additionalProperties": False},
     "_meta": {"mixar/domain": "account"}},
]


class FakeConnector:
    def __init__(self):
        self.tasks, self.calls = set(), []

    def catalog(self):
        return json.loads(json.dumps(BACKEND_TOOLS))

    def call(self, name, arguments, call_id):
        self.calls.append((name, arguments))
        payload = {"result": {"domains": {"build": 1}, "tools": [
            {"name": "execute_bpy_script", "domain": "build", "summary": "Run bpy.",
             "read_only": False, "credits": "free."}]}, "usage": {"request_id": call_id}}
        return {"content": [{"type": "text", "text": json.dumps(payload)}],
                "structuredContent": payload, "isError": False}

    def cancel(self, call_id=None):
        pass


def run(check):
    connector = FakeConnector()

    async def main():
        async with Client(stdio_server.create_server(connector)) as client:
            await check(client, connector)
    asyncio.run(main())


#: Claude Code keeps only this many characters of server instructions and of
#: each tool description; the full playbook is the backend's mixar_guide tool.
CLAUDE_CODE_TEXT_CAP = 2048


def test_instructions_teach_the_scene_workflow_within_claude_codes_cap():
    assert len(stdio_server.GUIDE) <= CLAUDE_CODE_TEXT_CAP
    for tool in ("mixar_guide", "mixar_scene_new", "scene_overview", "execute_bpy_script",
                 "render_viewport", "enqueue_generation", "get_all_queue_status",
                 "create_layered_material", "mixar_call_status"):
        assert tool in stdio_server.GUIDE
    flat = " ".join(stdio_server.GUIDE.split())
    assert "Splat worlds (world_labs) and videos only when the user wants one" in flat
    assert "Ask the user when an open choice matters" in flat and "never use OS-level computer use" in flat
    assert 'Choose each part\'s approach by judgement (notes in mixar_guide("generate"))' in flat
    from mixar.modules.common.ui_control.core import schema
    assert all(len(tool["description"]) <= CLAUDE_CODE_TEXT_CAP for tool in schema.tools())


def test_backend_discovery_hints_survive_the_launcher():
    async def check(client, connector):
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert tools["execute_bpy_script"].meta["anthropic/alwaysLoad"] is True
        assert tools["mixar_ui_act"].meta["mixar/domain"] == "ui"
        assert tools["mixar_tool_catalog"].input_schema["properties"]["domain"]["enum"][-2:] == ["ui", "scenes"]
        assert tools["mixar_scene_new"].meta["mixar/domain"] == "scenes"
    run(check)


def test_catalog_index_merges_ui_tools_and_answers_the_ui_domain_locally():
    async def check(client, connector):
        merged = (await client.call_tool("mixar_tool_catalog", {})).structured_content["result"]
        assert merged["domains"] == {"build": 1, "ui": 5, "scenes": 5}
        assert {"mixar_ui_observe", "execute_bpy_script"} <= {entry["name"] for entry in merged["tools"]}
        ui_only = (await client.call_tool("mixar_tool_catalog", {"domain": "ui"})).structured_content
        assert {entry["domain"] for entry in ui_only["result"]["tools"]} == {"ui"}
        assert len(connector.calls) == 1  # domain="ui" never reaches the backend
        build_only = (await client.call_tool("mixar_tool_catalog", {"domain": "build"})).structured_content
        assert "ui" not in build_only["result"]["domains"]
    run(check)
