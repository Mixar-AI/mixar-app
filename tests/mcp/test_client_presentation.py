# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Codex's direct MCP route sends its model only structuredContent, dropping images.

So for Codex a result with images omits structuredContent and the pictures reach
the model. Text is never shortened: Codex's code-mode scripts print what they
read, and a summary line hid results from the model. Other clients are unchanged.
"""

import asyncio
import json

from mcp import Client
from mcp.types import Implementation

from mixar.modules.mcp_bridge.core import stdio_server

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
SCRIPT_RESULT = {"result": {"message": "OK. created_objects: ['Offering tray', 'Brass kalash pot']\nStderr: warning",
                            "effects": {"created_objects": ["Offering tray", "Brass kalash pot"]}},
                 "usage": {"request_id": "x", "credits_charged": 1, "remaining_credits": 5157}}
RENDER_RESULT = {"result": "OK. quality: final, engine: CYCLES, width: 1000", "usage": {"credits_charged": 0}}


class FakeConnector:
    def __init__(self):
        self.tasks = set()

    def catalog(self):
        envelope = {"type": "object", "properties": {"result": {}, "usage": {"type": "object"}},
                    "required": ["result", "usage"]}
        return [{"name": name, "description": "Mixar tool.", "inputSchema": {"type": "object"},
                 "outputSchema": envelope, "_meta": {"mixar/domain": "verify"}}
                for name in ("render_viewport", "execute_bpy_script")]

    def call(self, name, arguments, call_id):
        payload = RENDER_RESULT if name == "render_viewport" else SCRIPT_RESULT
        content = [{"type": "text", "text": json.dumps(payload["result"])},
                   {"type": "text", "text": "Mixar usage: " + json.dumps(payload["usage"])}]
        if name == "render_viewport":
            content.append({"type": "image", "data": PNG, "mimeType": "image/png"})
        return {"content": content, "structuredContent": payload, "isError": False}

    def cancel(self, call_id=None):
        pass


def call(name, client_name):
    async def main():
        info = Implementation(name=client_name, version="1")
        async with Client(stdio_server.create_server(FakeConnector()), client_info=info) as client:
            return await client.call_tool(name, {"code": "print(1)"})
    return asyncio.run(main())


def test_codex_text_results_are_unchanged():
    result = call("execute_bpy_script", "codex-mcp-client")
    assert json.loads(result.content[0].text) == SCRIPT_RESULT["result"]
    assert result.structured_content == SCRIPT_RESULT


def test_codex_model_receives_images_because_structured_content_is_dropped():
    result = call("render_viewport", "codex-mcp-client")
    assert result.structured_content is None
    assert [block.type for block in result.content] == ["text", "text", "image"]


def test_other_clients_are_unchanged():
    for name in ("execute_bpy_script", "render_viewport"):
        result = call(name, "claude-code")
        assert result.structured_content is not None
        assert json.loads(result.content[0].text) == (SCRIPT_RESULT if name != "render_viewport"
                                                      else RENDER_RESULT)["result"]


def test_codex_is_never_sent_output_schemas_so_dropping_structured_content_is_valid():
    """A tool with an outputSchema must return structuredContent; strict MCP clients
    (the official SDK) reject the image result otherwise."""
    async def main(name):
        info = Implementation(name=name, version="1")
        async with Client(stdio_server.create_server(FakeConnector()), client_info=info) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            render = await client.call_tool("render_viewport", {})
            return tools, render
    tools, render = asyncio.run(main("codex-mcp-client"))
    assert all(tool.output_schema is None for tool in tools.values())
    assert render.structured_content is None and any(block.type == "image" for block in render.content)
    tools, _ = asyncio.run(main("claude-code"))
    assert tools["render_viewport"].output_schema is not None
