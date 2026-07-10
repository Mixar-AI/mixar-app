// Advanced UV tools — unwrap, pack islands, UV info

import { sendToBlender } from "../../blender-bridge.js";

export const uvTools = [
  {
    name: "blender_uv_unwrap",
    description:
      "UV unwrap a mesh object using the specified projection method. " +
      "SMART_PROJECT performs angle-based UV projection. UNWRAP uses the seam-based unwrap. " +
      "CUBE_PROJECT, CYLINDER_PROJECT, and SPHERE_PROJECT use geometric projections. " +
      "The object is switched to Edit Mode internally and returned to Object Mode after. " +
      "Returns the active UV layer name and the method used. " +
      "Example call: { \"object_name\": \"Cube\", \"method\": \"SMART_PROJECT\", \"angle_limit\": 66, \"island_margin\": 0.02 }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to UV unwrap.",
        },
        method: {
          type: "string",
          enum: [
            "SMART_PROJECT",
            "UNWRAP",
            "CUBE_PROJECT",
            "CYLINDER_PROJECT",
            "SPHERE_PROJECT",
          ],
          description: "UV unwrapping method to use. Must be UPPERCASE.",
        },
        angle_limit: {
          type: "number",
          description:
            "Angle limit in degrees for SMART_PROJECT. " +
            "Faces with a sharper angle than this are split into separate UV islands. Defaults to 66°.",
        },
        island_margin: {
          type: "number",
          description:
            "Margin between UV islands (0–1 range). Defaults to 0.02. " +
            "Used by SMART_PROJECT and UNWRAP.",
        },
      },
      required: ["object_name", "method"],
    },
    handler: async (args) => {
      const result = await sendToBlender("uv/unwrap", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_uv_pack_islands",
    description:
      "Pack UV islands for a mesh object to maximize UV space usage. " +
      "Optionally rotates islands for a better fit. " +
      "Returns the margin used and an estimate of the UV island count.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object whose UVs will be packed.",
        },
        margin: {
          type: "number",
          description: "Margin between packed UV islands (0–1 range). Defaults to 0.001.",
        },
        rotate: {
          type: "boolean",
          description:
            "Allow islands to be rotated during packing for a better fit. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Defaults to true.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("uv/pack-islands", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_uv_info",
    description:
      "Get UV layer information for a mesh object. " +
      "Returns all UV layer names, the active layer, whether the mesh has UVs, " +
      "and per-layer statistics including UV coverage and loop count.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to query UV information for.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("uv/info", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_uv_mark_seam",
    description:
      "Mark or clear UV seams on a mesh object. Seams guide the UNWRAP method to split UV islands. " +
      "Supports marking seams on sharp edges, by angle threshold, or clearing all seams. " +
      "Returns the object name and the number of edges affected.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to mark seams on.",
        },
        mode: {
          type: "string",
          enum: ["MARK_SHARP", "MARK_BY_ANGLE", "CLEAR_ALL"],
          description:
            "Seam marking mode. MARK_SHARP marks edges flagged as sharp. " +
            "MARK_BY_ANGLE marks edges where the face angle exceeds angle_threshold. " +
            "CLEAR_ALL removes all seams. Defaults to MARK_BY_ANGLE.",
        },
        angle_threshold: {
          type: "number",
          description:
            "Angle threshold in degrees for MARK_BY_ANGLE mode. " +
            "Edges with a face angle sharper than this are marked as seams. Defaults to 30.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("uv/mark-seam", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
