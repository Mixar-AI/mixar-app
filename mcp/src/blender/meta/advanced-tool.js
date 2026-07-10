// AnkleBreaker Blender MCP — Advanced Tool Gateway (Meta Tool)
// Skeleton for Vague 2. The actual implementation is in tool-tiers.js (advancedTool).
// This file provides the structure for future standalone meta-tool extraction.

/**
 * Advanced tool gateway handler.
 * Currently a placeholder — the actual dispatch logic lives in tool-tiers.js
 * as part of the splitToolTiers() function.
 *
 * In Vague 2, this may be extracted as a standalone module if the gateway
 * logic grows more complex.
 */
export const advancedToolInfo = {
  name: "blender_advanced_tool",
  description:
    "Execute an advanced/specialized Blender tool by name. Use blender_list_advanced_tools " +
    "to discover available tools and their parameters.",
  inputSchema: {
    type: "object",
    properties: {
      tool: {
        type: "string",
        description:
          'The tool name to execute (e.g. "blender_node_create", "blender_physics_add")',
      },
      params: {
        type: "object",
        description: "Parameters to pass to the tool.",
        additionalProperties: true,
      },
    },
    required: ["tool"],
  },
};
