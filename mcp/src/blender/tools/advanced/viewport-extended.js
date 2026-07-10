// Advanced viewport tools — blender_render_preview

import { sendToBlender } from "../../blender-bridge.js";

export const viewportExtendedTools = [
  {
    name: "blender_render_preview",
    description:
      "Quick Eevee render at low resolution for preview. " +
      "Example call: { \"filepath\": \"C:/tmp/preview.png\", \"resolution_percentage\": 50, \"samples\": 16 }.",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description: "Absolute path for the output render image (e.g. /tmp/preview.png).",
        },
        resolution_percentage: {
          type: "integer",
          description: "Render resolution percentage (1-100). Defaults to 50.",
        },
        samples: {
          type: "integer",
          maximum: 10000,
          description: "Number of Eevee render samples. Defaults to 16.",
        },
      },
      required: ["filepath"],
    },
    handler: async (args) => {
      const result = await sendToBlender("viewport/render-preview", {
        filepath: args.filepath,
        resolution_percentage: args.resolution_percentage ?? 50,
        samples: args.samples ?? 16,
      });
      return JSON.stringify(result, null, 2);
    },
  },
];
