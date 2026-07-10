// Validation tools — blender_validate_mesh, blender_validate_export_ready

import { sendToBlender } from "../../blender-bridge.js";

export const validationTools = [
  {
    name: "blender_validate_mesh",
    description:
      "Validate the mesh quality of an object with configurable checks. " +
      "Available checks: manifold, normals, ngons, poles, degenerate, loose, uvs, scale, doubles. " +
      "Example call: { \"object_name\": \"Cube\", \"checks\": [\"manifold\", \"normals\", \"uvs\"] }. " +
      "Returns: { object_name, overall_status, checks: [{ name, status, details }, ...] }",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to validate. Example: \"Table\".",
        },
        checks: {
          type: "array",
          items: {
            type: "string",
            enum: ["manifold", "normals", "ngons", "poles", "degenerate", "loose", "uvs", "scale", "doubles"],
          },
          description:
            "JSON array of check name strings to perform. Omit to run all checks. " +
            "IMPORTANT: Must be a JSON array of strings, NOT a string. " +
            "Valid values: \"manifold\", \"normals\", \"ngons\", \"poles\", \"degenerate\", \"loose\", \"uvs\", \"scale\", \"doubles\". " +
            "Example: [\"manifold\", \"normals\", \"uvs\"].",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("validation/mesh", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_validate_export_ready",
    description:
      "Run a pre-export readiness checklist on one or all mesh objects. " +
      "Validates applied transforms, clean normals, UV maps, no N-gons, manifold geometry, " +
      "proper scale, and material assignments. " +
      "Example call: { \"object_name\": \"Table\", \"target\": \"UNITY\" }. " +
      "Returns: { overall_status, objects: [{ name, status, checks: [{ name, status, details }, ...] }] }",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description:
            "Name of the mesh object to validate. " +
            "If omitted, all mesh objects in the scene are validated. Example: \"Table\".",
        },
        target: {
          type: "string",
          enum: ["UNITY", "UNREAL", "GLTF", "GENERIC"],
          description:
            "Target engine or format for which to validate. Must be UPPERCASE. " +
            "Affects which checks are required vs advisory. " +
            "Example: \"UNITY\".",
        },
      },
    },
    handler: async (args) => {
      const result = await sendToBlender("validation/export-ready", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
