# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Official SDK stdio endpoint combining local UI and existing backend tools."""

import asyncio
import json
import uuid

from mcp import types
from mcp.server import Server, NotificationOptions
from mcp.server.stdio import stdio_server

from mixar.modules.common.ui_control.core import schema
from .connector import Connector, instances

GUIDE = """Use Mixar scene tools for scripting and its UI tools for native interaction.
Observe before acting. Use returned context/target handles, then inspect state
and pixels to verify results. Human input interrupts control. Local UI calls cost
zero invocation credits; UI-triggered generation keeps normal product pricing.
Keep each call UUID: after an uncertain UI action use mixar_ui_call_status; for
backend scene tools use mixar_call_status. Never blindly repeat a mutation.
Mixar must be signed in; its bundled controller starts automatically with MCP.
"""


def failure(exc, call_id):
    payload = {"error": str(exc), "call_id": call_id,
               "note": "No automatic mutation retry occurred. Inspect status before further edits."}
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload))],
                                structured_content=payload, is_error=True,
                                meta={"mixar/request-id": call_id})


def create_server(connector):
    watcher = None

    async def watch_ready(session):
        delay = 1
        for _ in range(12):
            await asyncio.sleep(delay)
            try:
                await asyncio.to_thread(connector.catalog)
                await session.send_tool_list_changed()
                return
            except (OSError, ValueError, KeyError, RuntimeError, TimeoutError):
                delay = min(15, delay*2)

    async def list_tools(ctx, params):
        nonlocal watcher
        tools = schema.tools()
        try:
            tools += await asyncio.wait_for(asyncio.to_thread(connector.catalog), timeout=7)
        except (OSError, ValueError, KeyError, RuntimeError, TimeoutError):
            # Local readiness tools work before GUI/backend startup. Refresh the
            # host's catalog automatically when the desktop becomes available.
            if watcher is None or watcher.done():
                watcher = asyncio.create_task(watch_ready(ctx.session))
                connector.tasks.add(watcher)
                watcher.add_done_callback(connector.tasks.discard)
        return types.ListToolsResult(tools=[types.Tool.model_validate(t) for t in tools])

    async def call_tool(ctx, params):
        call_id = str(uuid.uuid4())
        try:
            call_id = str(uuid.UUID((ctx.meta or {}).get("mixar/request-id", call_id)))
            args = params.arguments or {}
            if params.name in schema.SCHEMAS:
                schema.validate(params.name, args)
            if params.name == "mixar_ui_context":
                if args.get("instance"):
                    available = await asyncio.to_thread(instances)
                    if args["instance"] not in {r["instance_id"] for r, _ in available}:
                        raise ValueError("Selected Mixar instance is unavailable")
                    await asyncio.to_thread(connector.cancel)
                    with connector.lock:
                        connector.instance, connector.record = args["instance"], None
                        connector.upstream_version = None
                    args = {k: v for k, v in args.items() if k != "instance"}
                elif connector.record is None:
                    available = await asyncio.to_thread(instances)
                    if len(available) > 1 or (connector.instance and available and
                            connector.instance not in {r["instance_id"] for r, _ in available}):
                        result = {"instances": [{"instance": r["instance_id"],
                                  "scene_name": h.get("scene_name")} for r, h in available]}
                        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result))],
                                                    structured_content=result)
            result = await asyncio.to_thread(connector.call, params.name, args, call_id)
            return types.CallToolResult.model_validate(result)
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(connector.cancel, call_id))
            raise
        except Exception as exc:
            return failure(exc, call_id)

    async def list_resources(ctx, params):
        return types.ListResourcesResult(resources=[types.Resource(uri="mixar://guide", name="Mixar guide",
                                                                   mime_type="text/markdown")])

    async def read_resource(ctx, params):
        if str(params.uri) != "mixar://guide":
            raise ValueError("Unknown Mixar resource")
        return types.ReadResourceResult(contents=[types.TextResourceContents(
            uri=params.uri, mime_type="text/markdown", text=GUIDE)])

    async def list_prompts(ctx, params):
        return types.ListPromptsResult(prompts=[types.Prompt(name="build-and-verify",
            description="Inspect, build with scene tools and native UI, and verify the result.",
            arguments=[types.PromptArgument(name="goal", required=True)])])

    async def get_prompt(ctx, params):
        args = params.arguments or {}
        goal = args.get("goal", "")
        if (params.name != "build-and-verify" or set(args) != {"goal"}
                or not goal.strip() or len(goal) > 8000):
            raise ValueError("Specify build-and-verify with a nonempty goal of at most 8000 characters")
        return types.GetPromptResult(messages=[types.PromptMessage(role="user",
            content=types.TextContent(type="text", text="Complete this task in Mixar: " + goal +
                "\n\n" + GUIDE + "Inspect scene state and screenshots before and after editing. "
                "Check tool costs and report credits and any unverified outcomes."))])

    return Server("Mixar", version="1", instructions=GUIDE,
                  on_list_tools=list_tools, on_call_tool=call_tool,
                  on_list_resources=list_resources, on_read_resource=read_resource,
                  on_list_prompts=list_prompts, on_get_prompt=get_prompt)


async def run(instance=None, session=None):
    connector = Connector(instance, session)
    server = create_server(connector)
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options(
                notification_options=NotificationOptions(tools_changed=True)))
    finally:
        for task in list(connector.tasks):
            task.cancel()
        if connector.tasks:
            await asyncio.gather(*connector.tasks, return_exceptions=True)
        await asyncio.to_thread(connector.cancel)
