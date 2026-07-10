<!-- SPDX-FileCopyrightText: 2026 AnkleBreaker Studio -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Mixar MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server that **replaces Mixar's hosted Mixie agent** with direct control from any MCP client — Claude Code, Claude Desktop, Cursor, or any other MCP-capable assistant. Built by [AnkleBreaker Studio](https://github.com/AnkleBreaker-Studio), following the same architecture as our Blender MCP.

## Why

Mixar's stock AI agent is a hosted LangGraph orchestrator: every chat turn burns Mixar agent tokens/credits, and the LLM loop runs on their servers. With this MCP:

- **Zero agent tokens** — the MCP client (e.g. Claude) *is* the orchestrator. Scripts execute through the exact same sandboxed in-app executor the hosted agent uses, with identical undo grouping, scene-change diffing, and `__PARAMS__`/`__RESULT__` conventions.
- **Full control** — anything the hosted agent could do (modeling, texturing, UV, scene management, paint layers) plus everything it couldn't (arbitrary sandboxed bpy scripting on demand).
- **Key-provider integration** — manage BYOK provider credentials (`mixar_provider_keys`) so GPU generation jobs bill the user's own OpenAI/Anthropic/other account instead of Mixar credits.

## Architecture

```
Claude / MCP client ←stdio→ Mixar MCP Server (this dir) ←HTTP 127.0.0.1:9877→ MCP bridge inside Mixar
                                                            (src/scripts/mixar/modules/mcp_bridge)
```

The in-app bridge ships with Mixar itself (enabled by default; `MIXAR_MCP_ENABLED=0` disables it). It binds loopback only and **always requires a shared token**.

### Security model

The bridge is a local-control surface, hardened against browser-driven CSRF / DNS-rebinding:

- **Token always required.** If `MIXAR_MCP_TOKEN` is unset, the bridge generates a random token at startup and writes it to a file under Blender's config dir (`.../config/mixar/mcp_bridge_token`). This MCP server reads it automatically; set `MIXAR_MCP_TOKEN` on both sides to pin an explicit value.
- **JSON-only.** POSTs must be `Content-Type: application/json`, which forces a CORS preflight the server never answers — so a web page can't reach it with a "simple" cross-origin request.
- **No `Origin`, loopback `Host` only.** Requests carrying an `Origin` header, or a non-loopback `Host`, are rejected (403).
- **Loopback bind enforced.** The server refuses to bind any non-loopback host; the Node client refuses to connect to one.

## Tools

Two families. **Mixar is a Blender 5.0 fork**, so this server ships the entire AnkleBreaker Blender MCP tool surface *plus* Mixar-native tools — one MCP, full control.

### Mixar-native (`mixar_*`, 11)

| Tool | Purpose |
|---|---|
| `mixar_health` | Bridge connectivity + app version |
| `mixar_execute_script` | **Full-control** sandboxed bpy script execution (params in, `__RESULT__` out) |
| `mixar_scene_info` | Active scene snapshot (objects, transforms, visibility) |
| `mixar_object_info` | Deep info for one object (mesh stats, modifiers, materials) |
| `mixar_scene_graph` | Hierarchy queries: summary/roots/children/descendants/ancestors/describe |
| `mixar_operation_history` | Local log of all agent scripts + manual ops (read/replay) |
| `mixar_generation_catalog` | Capabilities → services → models with param schemas |
| `mixar_generate` | Submit GPU generation jobs (image gen, 3D gen, retopo, UV, textures...) |
| `mixar_generation_job_status` | Poll jobs; returns result URLs when DONE |
| `mixar_generation_job_cancel` | Cancel a job |
| `mixar_provider_keys` | BYOK: status / models / set / remove provider API keys |

### Blender surface (`blender_*`, 236 — two-tier)

The full Blender editing toolset, vendored from our Blender MCP and pointed at Mixar's in-app bridge. To keep the client's tool list manageable, it uses a **two-tier** system: **52 core tools** are exposed directly, and **184 advanced tools** sit behind a proxy.

- **Core (direct):** scene, object, mesh, material, modifier, render, animation, file, collection, export/import, validation, reference (dimensions/materials/recipes), analysis, viewport.
- **Advanced (via proxy):** modeling, UV, sculpt, armature, curve, light, camera, texture, particle, physics, constraint, node graphs, grease pencil, text, lattice, vertex groups, addons, extended render/animation/export, and more.
- `blender_list_advanced_tools` — discover advanced tools by category.
- `blender_advanced_tool` — invoke any advanced tool by name with its params.

Every Blender op runs on Blender's main thread through the same serialized path as `mixar_execute_script` (no concurrent bpy access), with `render/physics/bake/export` routes getting an extended timeout.

**Total: 247 tools across both families, exposed as 65** (11 Mixar + 52 Blender core + 2 proxy meta-tools).

## Quick Start

```bash
cd mcp && npm install
```

Claude Desktop / Claude Code config:

```json
{
  "mcpServers": {
    "mixar": {
      "command": "node",
      "args": ["C:/path/to/mixar-app/mcp/src/index.js"]
    }
  }
}
```

Launch Mixar, then ask: *"What's in my Mixar scene?"* → *"Model a low-poly house with a red roof"*.

## Configuration

| Env var | Default | Where | Description |
|---|---|---|---|
| `MIXAR_MCP_ENABLED` | `1` | Mixar app | Set `0` to disable the in-app bridge |
| `MIXAR_MCP_HOST` | `127.0.0.1` | both | Bridge bind/connect host |
| `MIXAR_MCP_PORT` | `9877` | both | Bridge port (9876 is our Blender MCP — they coexist) |
| `MIXAR_MCP_TOKEN` | *(auto-generated)* | both | Shared secret (`X-Mixar-MCP-Token`); auto-generated to a token file if unset |
| `MIXAR_MCP_TIMEOUT` | `620000` | MCP server | HTTP timeout (ms) |
| `MIXAR_MCP_ALLOW_PYTHON_EXEC` | `1` | MCP server | Set `0` to disable the raw `blender_python_*` exec tools (sandboxed `mixar_execute_script` still available) |

## What still needs a Mixar account

Script execution, scene graph, and operation history are **fully local** — no login, no backend. GPU generation (`mixar_generate`), the catalog, and BYOK ride the user's existing Mixar session against whatever `backend_url` the app is configured with; log into Mixar once in-app and they just work.

## License

GPL-3.0-or-later (part of the Mixar fork).
