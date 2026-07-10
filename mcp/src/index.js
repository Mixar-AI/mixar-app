#!/usr/bin/env node
// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// Mixar MCP Server — entry point.
// Replaces Mixar's hosted Mixie agent: the MCP client (Claude Code/Desktop,
// or any MCP-capable assistant) becomes the orchestrator and drives Mixar
// directly. Because Mixar is a Blender 5.0 fork, this server exposes BOTH:
//   * Mixar-native tools (mixar_*): sandboxed scripting, generation queue, BYOK
//   * the full AnkleBreaker Blender MCP surface (blender_*): 44 core tools +
//     ~180 advanced tools behind a two-tier proxy — vendored from our Blender
//     MCP and pointed at Mixar's in-app bridge.

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import { CONFIG } from "./config.js";

// ─── Mixar-native tools ───
import { systemTools } from "./tools/system.js";
import { executeTools } from "./tools/execute.js";
import { sceneTools as mixarSceneTools } from "./tools/scene.js";
import { historyTools } from "./tools/history.js";
import { generationTools } from "./tools/generation.js";
import { providerTools } from "./tools/providers.js";

// ─── Vendored Blender tool surface (two-tier) ───
import { splitToolTiers } from "./blender/tool-tiers.js";
import { validateParams } from "./blender/validate-params.js";
import { loadReferenceData } from "./blender/reference/loader.js";

// Core Blender tools
import { fileTools } from "./blender/tools/core/file.js";
import { sceneTools } from "./blender/tools/core/scene.js";
import { objectTools } from "./blender/tools/core/object.js";
import { collectionTools } from "./blender/tools/core/collection.js";
import { materialTools } from "./blender/tools/core/material.js";
import { modifierTools } from "./blender/tools/core/modifier.js";
import { meshTools } from "./blender/tools/core/mesh.js";
import { renderTools } from "./blender/tools/core/render.js";
import { animationTools } from "./blender/tools/core/animation.js";
import { exportTools } from "./blender/tools/core/export.js";
import { validationTools } from "./blender/tools/core/validation.js";
import { referenceTools } from "./blender/tools/core/reference.js";
import { analysisTools } from "./blender/tools/core/analysis.js";
import { viewportTools } from "./blender/tools/core/viewport.js";

// Advanced Blender tools
import { exportExtendedTools } from "./blender/tools/advanced/export-extended.js";
import { validationExtendedTools } from "./blender/tools/advanced/validation-extended.js";
import { pythonExecTools } from "./blender/tools/advanced/python-exec.js";
import { modelingTools } from "./blender/tools/advanced/modeling.js";
import { uvTools } from "./blender/tools/advanced/uv.js";
import { referenceExtendedTools } from "./blender/tools/advanced/reference-extended.js";
import { analysisExtendedTools } from "./blender/tools/advanced/analysis-extended.js";
import { viewportExtendedTools } from "./blender/tools/advanced/viewport-extended.js";
import { sculptTools } from "./blender/tools/advanced/sculpt.js";
import { armatureTools } from "./blender/tools/advanced/armature.js";
import { animationExtendedTools } from "./blender/tools/advanced/animation-extended.js";
import { nodeTools } from "./blender/tools/advanced/node.js";
import { curveTools } from "./blender/tools/advanced/curve.js";
import { lightTools } from "./blender/tools/advanced/light.js";
import { cameraTools } from "./blender/tools/advanced/camera.js";
import { textureTools } from "./blender/tools/advanced/texture.js";
import { particleTools } from "./blender/tools/advanced/particle.js";
import { physicsTools } from "./blender/tools/advanced/physics.js";
import { constraintTools } from "./blender/tools/advanced/constraint.js";
import { renderExtendedTools } from "./blender/tools/advanced/render-extended.js";
import { greasePencilTools } from "./blender/tools/advanced/grease-pencil.js";
import { textObjectTools } from "./blender/tools/advanced/text.js";
import { latticeTools } from "./blender/tools/advanced/lattice.js";
import { vertexGroupTools } from "./blender/tools/advanced/vertex-group.js";
import { addonTools } from "./blender/tools/advanced/addon.js";
import { coreExtendedTools } from "./blender/tools/advanced/core-extended.js";

// ─── Assemble ───
const mixarTools = [
  ...systemTools,
  ...executeTools,
  ...mixarSceneTools,
  ...historyTools,
  ...generationTools,
  ...providerTools,
];

const allBlenderTools = [
  ...fileTools,
  ...sceneTools,
  ...objectTools,
  ...collectionTools,
  ...materialTools,
  ...modifierTools,
  ...meshTools,
  ...renderTools,
  ...animationTools,
  ...exportTools,
  ...validationTools,
  ...referenceTools,
  ...analysisTools,
  ...viewportTools,
  ...exportExtendedTools,
  ...validationExtendedTools,
  ...pythonExecTools,
  ...modelingTools,
  ...uvTools,
  ...referenceExtendedTools,
  ...analysisExtendedTools,
  ...viewportExtendedTools,
  ...sculptTools,
  ...armatureTools,
  ...animationExtendedTools,
  ...nodeTools,
  ...curveTools,
  ...lightTools,
  ...cameraTools,
  ...textureTools,
  ...particleTools,
  ...physicsTools,
  ...constraintTools,
  ...renderExtendedTools,
  ...greasePencilTools,
  ...textObjectTools,
  ...latticeTools,
  ...vertexGroupTools,
  ...addonTools,
  ...coreExtendedTools,
];

const { coreTools, metaTools, advancedCount, coreCount } = splitToolTiers(allBlenderTools);
const ALL_TOOLS = [...mixarTools, ...coreTools, ...metaTools];

console.error(
  `[MCP] Mixar tools: ${mixarTools.length} | Blender tiers: ${coreCount} core + ` +
    `${advancedCount} advanced (via blender_advanced_tool) | ${ALL_TOOLS.length} exposed`
);

const server = new Server(
  { name: "mixar-mcp-server", version: "0.2.0" },
  {
    capabilities: { tools: {} },
    instructions: [
      "You are driving Mixar (a Blender 5.0 fork) directly — you replace its hosted AI agent.",
      "Two tool families: mixar_* (sandboxed scripting, generation queue, BYOK keys) and",
      "blender_* (the full Blender editing surface — scene/object/mesh/material/modifier/render/",
      "animation/UV/sculpt/armature/node/physics/etc.). Use blender_list_advanced_tools +",
      "blender_advanced_tool to reach specialized tools. Never call the HTTP bridge directly.",
      "Understand the scene with mixar_scene_info / blender_scene_info, then act with the",
      "structured blender_* tools or mixar_execute_script for arbitrary bpy.",
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
    `Mixar MCP Server v0.2.0 on stdio — ${ALL_TOOLS.length} tools (bridge: ${CONFIG.mixarHost}:${CONFIG.mixarPort})`
  );
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
