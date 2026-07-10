#!/usr/bin/env node
// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// Mixar MCP Server — entry point.
// Replaces Mixar's hosted Mixie agent: the MCP client (Claude Code/Desktop,
// or any MCP-capable assistant) becomes the orchestrator and drives Mixar's
// sandboxed script executor, scene graph, operation history, generation
// queue, and BYOK key-provider settings directly.

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import { CONFIG } from "./config.js";
import { systemTools } from "./tools/system.js";
import { executeTools } from "./tools/execute.js";
import { sceneTools } from "./tools/scene.js";
import { historyTools } from "./tools/history.js";
import { generationTools } from "./tools/generation.js";
import { providerTools } from "./tools/providers.js";

const ALL_TOOLS = [
  ...systemTools,
  ...executeTools,
  ...sceneTools,
  ...historyTools,
  ...generationTools,
  ...providerTools,
];

const server = new Server(
  { name: "mixar-mcp-server", version: "0.1.0" },
  {
    capabilities: { tools: {} },
    instructions: [
      "You are driving Mixar (a Blender 5.0 fork) directly — you replace its hosted AI agent.",
      "Use the mixar_* MCP tools for all Mixar operations; never call the HTTP bridge directly.",
      "Workflow: mixar_scene_info / mixar_scene_graph to understand the scene, then",
      "mixar_execute_script for any modeling/texturing/scene change (set __RESULT__ for data),",
      "mixar_generate + mixar_generation_job_status for GPU generation (import results via script),",
      "and mixar_provider_keys to manage BYOK provider credentials.",
    ].join(" "),
  }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: ALL_TOOLS.map(({ name, description, inputSchema }) => ({
    name,
    description,
    inputSchema,
  })),
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const tool = ALL_TOOLS.find((t) => t.name === name);
  if (!tool) {
    return {
      content: [{ type: "text", text: `Unknown tool: ${name}` }],
      isError: true,
    };
  }

  // Validate required fields before forwarding to the bridge.
  const required = tool.inputSchema?.required || [];
  for (const field of required) {
    if (args?.[field] === undefined || args?.[field] === null) {
      return {
        content: [{ type: "text", text: `Missing required parameter: ${field}` }],
        isError: true,
      };
    }
  }

  try {
    const result = await tool.handler(args || {});
    return { content: [{ type: "text", text: result }] };
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
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(
    `Mixar MCP Server v0.1.0 on stdio — ${ALL_TOOLS.length} tools (bridge: ${CONFIG.mixarHost}:${CONFIG.mixarPort})`
  );
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
