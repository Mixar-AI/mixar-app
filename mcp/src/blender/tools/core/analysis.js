// Analysis tools — blender_analyze_mesh

import { sendToBlender } from "../../blender-bridge.js";

export const analysisTools = [
  {
    name: "blender_analyze_mesh",
    description:
      "Comprehensive mesh analysis: geometry stats, bounding box, quality metrics, materials, UVs, modifiers. " +
      "Example call: { \"object_name\": \"Table\" }. " +
      "Returns: { name, vertex_count, edge_count, face_count, triangle_count, bounding_box, quality_metrics, materials, uv_layers, modifiers }",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to analyze. Example: \"Cube\".",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("analysis/mesh", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
