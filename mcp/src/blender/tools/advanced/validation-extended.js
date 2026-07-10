// Advanced validation tools — blender_validate_scene

import { sendToBlender } from "../../blender-bridge.js";

export const validationExtendedTools = [
  {
    name: "blender_validate_scene",
    description:
      "Run a full scene-wide validation pass across all objects. " +
      "Checks naming conventions, applied transforms, material assignments, " +
      "orphan data blocks, and visibility coherence. " +
      "Returns a per-object summary with warnings and errors. " +
      "Example call: { \"checks\": [\"naming\", \"transforms\"] }.",
    inputSchema: {
      type: "object",
      properties: {
        checks: {
          type: "array",
          items: {
            type: "string",
            enum: ["naming", "transforms", "materials", "orphans", "visibility"],
          },
          description:
            "Optional list of specific checks to run. " +
            "IMPORTANT: Must be a JSON array of strings, NOT a string. " +
            "Example: [\"naming\", \"transforms\"]. Omit to run all checks. " +
            "Valid values: naming, transforms, materials, orphans, visibility.",
        },
      },
    },
    handler: async (args) => {
      const result = await sendToBlender("validation/scene", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
