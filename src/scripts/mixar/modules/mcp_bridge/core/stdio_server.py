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
from . import presentation
from .connector import Connector, instances

# Clients put server instructions in the model's system prompt, and Claude Code
# keeps only their first 2,048 characters: core rules first, the full playbook
# is the backend's free mixar_guide tool.
GUIDE = """\
Mixar is an AI-native 3D editor built on Blender 5.2. These tools act on the
user's open, signed-in Mixar desktop. Call mixar_guide first, then
mixar_guide(topic) before planning that kind of work (build, generate,
characters, environments, materials, delivery).

Each connection works in one scene tab; every tool and generation result
follows it. Start separate work in a new tab with
mixar_scene_new (never bpy.data.scenes.new); mixar_scenes and
mixar_scene_switch move between tabs; mixar_projects and mixar_project_open
continue a saved project.

1. Inspect: scene_overview, then scene_hierarchy or get_object_details.
2. Build in small steps with execute_bpy_script: one part per script, real
   size in metres, exact names, print what you check.
3. Verify every visible change with render_viewport and inspect_geometry; fix
   problems first and never report what you have not seen.
4. Choose each part's approach by judgement (notes in mixar_guide("generate")):
   scripts, existing assets or AI generation, which usually suits organic
   subjects. Ask when the choice matters and the request does not settle it.
   Splat worlds (world_labs) and videos only when the user wants one.
   enqueue_generation returns at once; check get_all_queue_status later and
   never resubmit a running job.
5. Before modelling props or plants, try search_asset_library and
   list_terrain_assets. Realistic materials: create_layered_material.
6. Deliver with render_scene_image / render_scene_video or export_scene /
   export_asset.

Ask the user when an open choice matters (method, style, scale, detail, a
large credit spend); settle small details yourself.
Native UI tools (mixar_ui_*, if the user allows them) cover what no other
tool does; never use OS-level computer use on Mixar.
Inspection and UI input are free; scene edits cost Mixar credits (default 1)
and generation its job price. After an uncertain outcome, inspect and use
mixar_call_status or mixar_ui_call_status with the same call UUID; never
blindly repeat an edit.
"""
#: Domains of the tools this launcher serves locally (the backend never sees them).
LOCAL_DOMAINS = tuple(dict.fromkeys(schema.DOMAINS.values()))


def ui_index(query="", domain=None):
    """Compact catalog entries for the local tools."""
    query = query.casefold()
    entries = [{"name": tool["name"], "domain": tool["_meta"]["mixar/domain"],
                "summary": tool["description"].split(". ", 1)[0].rstrip(".") + ".",
                "read_only": tool["annotations"]["readOnlyHint"], "credits": "free."}
               for tool in schema.tools()
               if domain in (None, tool["_meta"]["mixar/domain"])
               and (query in tool["name"].casefold() or query in tool["description"].casefold())]
    return entries


def with_ui_domain(tools):
    """Let mixar_tool_catalog's advertised domain filter name the local domains."""
    for tool in tools:
        domain = tool.get("inputSchema", {}).get("properties", {}).get("domain")
        if tool["name"] == "mixar_tool_catalog" and domain:
            domain["enum"] = [*domain.get("enum", []),
                              *(name for name in LOCAL_DOMAINS if name not in domain.get("enum", []))]
    return tools


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
            tools += with_ui_domain(await asyncio.wait_for(asyncio.to_thread(connector.catalog), timeout=7))
            if getattr(connector, "health", {}).get("ui_control") is False:
                # Interface control is opt-in; scene and project tools stay.
                tools = [tool for tool in tools if tool["name"] not in schema.UI_INPUT]
        except (OSError, ValueError, KeyError, RuntimeError, TimeoutError):
            # Local readiness tools work before GUI/backend startup. Refresh the
            # host's catalog automatically when the desktop becomes available.
            if watcher is None or watcher.done():
                watcher = asyncio.create_task(watch_ready(ctx.session))
                connector.tasks.add(watcher)
                watcher.add_done_callback(connector.tasks.discard)
        tools = presentation.tools_for_client(tools, presentation.client_name(ctx))
        return types.ListToolsResult(tools=[types.Tool.model_validate(t) for t in tools])

    async def call_tool(ctx, params):
        result = await _call_tool(ctx, params)
        shaped = presentation.for_client(result.model_dump(by_alias=True, exclude_none=True),
                                         presentation.client_name(ctx))
        return types.CallToolResult.model_validate(shaped)

    async def _call_tool(ctx, params):
        call_id = str(uuid.uuid4())
        try:
            call_id = str(uuid.UUID((ctx.meta or {}).get("mixar/request-id", call_id)))
            args = params.arguments or {}
            if params.name in schema.SCHEMAS:
                schema.validate(params.name, args)
            if params.name == "mixar_tool_quote" and args.get("tool") in schema.SCHEMAS:
                if set(args) != {"tool"}:
                    raise ValueError("Specify only the tool to quote")
                payload = {"result": {"tool": args["tool"], "invocation_credits": 0,
                    "generation_credits": None, "generation_billing": "existing_job_queue",
                    "surface": "local_ui"}, "usage": {"request_id": call_id, "credits_charged": 0}}
                return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload))],
                                            structured_content=payload, meta={"mixar/request-id": call_id})
            if params.name == "mixar_ui_context":
                if args.get("instance"):
                    available = await asyncio.to_thread(instances)
                    if args["instance"] not in {r["instance_id"] for r, _ in available}:
                        raise ValueError("Selected Mixar instance is unavailable")
                    await asyncio.to_thread(connector.cancel)
                    with connector.lock:
                        connector.instance, connector.record = args["instance"], None
                        connector.upstream_version = None
                        connector.bound_session = connector.session
                    args = {k: v for k, v in args.items() if k != "instance"}
                elif connector.record is None:
                    available = await asyncio.to_thread(instances)
                    if len(available) > 1 or (connector.instance and available and
                            connector.instance not in {r["instance_id"] for r, _ in available}):
                        result = {"instances": [{"instance": r["instance_id"],
                                  "scene_name": h.get("scene_name")} for r, h in available]}
                        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result))],
                                                    structured_content=result)
                if args.get("session"):
                    _, health = await asyncio.to_thread(connector.attach)
                    if args["session"] != health.get("session_id"):
                        raise ValueError("Select the current Mixar scene session returned by context")
                    connector.bound_session = args["session"]
                    args = {k: v for k, v in args.items() if k != "session"}
            if params.name == "mixar_tool_catalog" and args.get("domain") in LOCAL_DOMAINS:
                entries = ui_index(args.get("query", ""), args["domain"])
                payload = {"result": {"domains": {args["domain"]: len(entries)}, "tools": entries},
                           "usage": {"request_id": call_id, "credits_charged": 0}}
                return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload))],
                                            structured_content=payload, meta={"mixar/request-id": call_id})
            result = await asyncio.to_thread(connector.call, params.name, args, call_id)
            if params.name == "mixar_tool_catalog" and not result.get("isError"):
                payload = result["structuredContent"]["result"]
                if "domains" in payload:
                    entries = ui_index(args.get("query", ""), args.get("domain"))
                    payload["tools"].extend(entries)
                    for entry in entries:
                        payload["domains"][entry["domain"]] = payload["domains"].get(entry["domain"], 0) + 1
                else:  # An older backend returns full tool definitions.
                    query = args.get("query", "").casefold()
                    payload["tools"].extend(t for t in schema.tools() if query in t["name"].casefold()
                                           or query in t["description"].casefold())
                result["content"][0] = {"type": "text", "text": json.dumps(payload)}
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
                "\n\n" + GUIDE + "Inspect the scene with Mixar's tools (render_viewport, mixar_ui_observe) before and after editing. "
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
