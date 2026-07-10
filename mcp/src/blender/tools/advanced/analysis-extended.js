// Advanced analysis tools — blender_analyze_batch

import { sendToBlender } from "../../blender-bridge.js";

export const analysisExtendedTools = [
  {
    name: "blender_analyze_batch",
    description:
      "Analyze mesh objects in the scene with pagination. " +
      "Returns summary and per-object details. Default limit is 50 to avoid timeouts on large scenes. " +
      "Returns: { summary: { total_objects_in_scene, analyzed_count, ... }, objects: [...] }. " +
      "Example call: { \"filter_type\": \"MESH\", \"limit\": 50, \"offset\": 0 }.",
    inputSchema: {
      type: "object",
      properties: {
        filter_type: {
          type: "string",
          description:
            "Optional object type filter. Defaults to MESH. Other values: CURVE, SURFACE, etc.",
        },
        limit: {
          type: "integer",
          description:
            "Maximum number of objects to analyze. Default 50, max 200. " +
            "Use with offset for pagination in large scenes.",
        },
        offset: {
          type: "integer",
          description:
            "Number of objects to skip before analyzing. Default 0. " +
            "Use with limit for pagination.",
        },
      },
    },
    handler: async (args) => {
      const result = await sendToBlender("analysis/batch", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
