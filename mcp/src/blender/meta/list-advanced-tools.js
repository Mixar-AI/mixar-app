// AnkleBreaker Blender MCP — List Advanced Tools (Meta Tool)
// Skeleton for Vague 2. The actual implementation is in tool-tiers.js (catalogTool).
// This file provides the structure for future standalone meta-tool extraction.

/**
 * List advanced tools handler.
 * Currently a placeholder — the actual catalog logic lives in tool-tiers.js
 * as part of the splitToolTiers() function.
 *
 * In Vague 2, this may be extracted as a standalone module if the meta-tool
 * logic grows more complex.
 */
export const listAdvancedToolsInfo = {
  name: "blender_list_advanced_tools",
  description:
    "List all available advanced/specialized Blender tools organized by category. " +
    "These tools are not directly exposed but can be called via blender_advanced_tool.",
  inputSchema: {
    type: "object",
    properties: {
      category: {
        type: "string",
        description:
          'Filter by category name (e.g. "node", "physics", "armature"). Omit for full list.',
      },
    },
  },
};
