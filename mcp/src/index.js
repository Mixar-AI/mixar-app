#!/usr/bin/env node
// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// Mixar MCP Server — entry point.
// Replaces Mixar's hosted Mixie agent: the MCP client (Claude Code/Desktop,
// or any MCP-capable assistant) becomes the orchestrator and drives Mixar
// directly. Because Mixar is a Blender 5.0 fork, this server exposes BOTH:
//   * Mixar-native tools (mixar_*): sandboxed scripting, generation queue, BYOK
//   * the full AnkleBreaker Blender MCP surface (blender_*): ~52 core tools +
//     ~184 advanced tools behind a two-tier proxy — vendored from our Blender
//     MCP and pointed at Mixar's in-app bridge. Every tool is annotated
//     (read-only/destructive/idempotent/open-world) at assembly time.

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import { readdirSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";

import { CONFIG } from "./config.js";
import { splitToolTiers } from "./blender/tool-tiers.js";
import { validateParams } from "./blender/validate-params.js";
import { loadReferenceData } from "./blender/reference/loader.js";
import { deriveAnnotations } from "./annotations.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

// Auto-discover tool modules: every .js in a tools directory that exports an
// array of {name, handler} tool defs is collected. Adding a tool is just
// dropping a file in the right directory — there is no hand-maintained import
// list or spread array to keep in sync (that was a real drift class), and no
// module can be silently forgotten.
async function loadToolArrays(dir) {
  const tools = [];
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".js")).sort()) {
    const mod = await import(pathToFileURL(join(dir, file)).href);
    for (const value of Object.values(mod)) {
      if (
        Array.isArray(value) &&
        value.length > 0 &&
        value.every((t) => t && typeof t.name === "string" && typeof t.handler === "function")
      ) {
        tools.push(...value);
      }
    }
  }
  return tools;
}

// ─── Assemble (glob-discovered) ───
const mixarTools = await loadToolArrays(join(__dirname, "tools"));
const allBlenderTools = [
  ...(await loadToolArrays(join(__dirname, "blender", "tools", "core"))),
  ...(await loadToolArrays(join(__dirname, "blender", "tools", "advanced"))),
];

const { coreTools, metaTools, advancedCount, coreCount } = splitToolTiers(allBlenderTools);
const ALL_TOOLS = [...mixarTools, ...coreTools, ...metaTools];

// O(1) dispatch — avoid a linear scan of ALL_TOOLS on every CallTool.
const TOOL_BY_NAME = new Map(ALL_TOOLS.map((t) => [t.name, t]));

// Drift guard: the core-tier membership set (CORE_TOOLS in tool-tiers.js) is a
// hardcoded name list. If an upstream rename drops a name, the tool silently
// demotes to advanced. Surface that instead of letting the "52 core" quietly rot.
const EXPECTED_CORE_MIN = 50;
if (coreCount < EXPECTED_CORE_MIN) {
  console.error(
    `[MCP] WARNING: only ${coreCount} core Blender tools resolved (expected >= ${EXPECTED_CORE_MIN}). ` +
      "A tool may have been renamed upstream and silently demoted to the advanced tier — " +
      "check CORE_TOOLS in blender/tool-tiers.js."
  );
}

// Precompute the ListTools payload (annotations included) once.
const LISTED_TOOLS = ALL_TOOLS.map(({ name, description, inputSchema }) => {
  const annotations = deriveAnnotations(name);
  return annotations ? { name, description, inputSchema, annotations } : { name, description, inputSchema };
});

console.error(
  `[MCP] Mixar tools: ${mixarTools.length} | Blender tiers: ${coreCount} core + ` +
    `${advancedCount} advanced (via blender_advanced_tool) | ${ALL_TOOLS.length} exposed | ` +
    `${LISTED_TOOLS.filter((t) => t.annotations).length} annotated`
);

const server = new Server(
  { name: "mixar-mcp-server", version: "0.3.0" },
  {
    capabilities: { tools: {} },
    instructions: [
      "You are driving Mixar (a Blender 5.0 fork) directly — you REPLACE its hosted AI agent, so",
      "you do the planning and tool selection yourself.",
      "",
      "TWO TOOL FAMILIES:",
      "• mixar_* — Mixar-native: mixar_execute_script (arbitrary sandboxed bpy: modules bpy/bmesh/",
      "mathutils/numpy available, but NO os/pathlib/eval/exec; return data by assigning a dict to",
      "__RESULT__), the generation queue (mixar_generate → mixar_generation_job_status), and",
      "mixar_provider_keys (BYOK).",
      "• blender_* — the full Blender editing surface. 52 common tools are exposed directly; ~184",
      "specialized ones are reachable via blender_list_advanced_tools (discover) + blender_advanced_tool",
      "(invoke by name).",
      "",
      "WORKFLOW: inspect first (mixar_scene_info / blender_scene_info / blender_object_info /",
      "mixar_scene_graph), then act with structured blender_* tools; drop to mixar_execute_script only",
      "for logic no structured tool covers. Prefer structured tools — they validate inputs and are",
      "annotated (read-only vs destructive).",
      "",
      "NOTES: Tools are annotated with readOnlyHint/destructiveHint/idempotentHint/openWorldHint — respect",
      "them (confirm destructive ops like deletes). The bridge serializes bpy access on one main thread,",
      "so a long render/bake blocks other calls and a busy bridge answers 'busy: true' — back off and",
      "retry, don't hammer. Call mixar_health first if tools fail. Never call the HTTP bridge directly.",
    ].join(" "),
  }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: LISTED_TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const tool = TOOL_BY_NAME.get(name);
  if (!tool) {
    return {
      content: [{ type: "text", text: `Unknown tool: ${name}` }],
      isError: true,
    };
  }

  // Centralized param validation (required fields + basic types) for every tool.
  const validation = validateParams(tool, args || {});
  if (!validation.valid) {
    return {
      content: [{ type: "text", text: validation.error }],
      isError: true,
    };
  }

  try {
    const result = await tool.handler(args || {});
    // Tool handlers return a plain string; arrays are already MCP content blocks.
    const content = Array.isArray(result) ? result : [{ type: "text", text: result }];
    return { content };
  } catch (error) {
    return {
      content: [{ type: "text", text: `Error executing ${name}: ${error.message}` }],
      isError: true,
    };
  }
});

let isShuttingDown = false;
async function shutdown() {
  if (isShuttingDown) return;
  isShuttingDown = true;
  try {
    await server.close();
  } catch (err) {
    console.error(`[MCP] Error closing server: ${err.message}`);
  }
  setTimeout(() => process.exit(0), 300);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

async function main() {
  loadReferenceData();
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(
    `Mixar MCP Server v0.3.0 on stdio — ${ALL_TOOLS.length} tools (bridge: ${CONFIG.mixarHost}:${CONFIG.mixarPort})`
  );
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
