// Animation tools — blender_anim_insert_keyframe, blender_anim_get_keyframes, blender_anim_set_frame

import { sendToBlender } from "../../blender-bridge.js";

export const animationTools = [
  {
    name: "blender_anim_insert_keyframe",
    description:
      "Insert a keyframe on a specific data path of an object at the given frame. " +
      "Common data paths: 'location', 'rotation_euler', 'scale'. " +
      "Custom paths such as 'data.energy' (for lights) are also supported. " +
      "Example call: { \"name\": \"Cube\", \"data_path\": \"location\", \"frame\": 1, \"value\": [0, 0, 0] }. " +
      "Returns: { success, name, data_path, frame, index }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "The exact name of the object to keyframe. Example: \"Cube\".",
        },
        data_path: {
          type: "string",
          description:
            "The property path to keyframe. " +
            "Common values: \"location\", \"rotation_euler\", \"scale\", \"data.energy\". " +
            "Example: \"location\".",
        },
        frame: {
          type: "integer",
          description:
            "Frame number at which to insert the keyframe. " +
            "Example: 1. Defaults to the current scene frame.",
        },
        index: {
          type: "integer",
          description:
            "0-based channel index: omit to key all channels of the property. " +
            "Use 0 for X, 1 for Y, 2 for Z. " +
            "Note: -1 is NOT supported. Example: 2 (Z channel only).",
        },
        value: {
          oneOf: [
            { type: "number" },
            { type: "array", items: { type: "number" } },
          ],
          description:
            "Optional value to assign to the property before inserting the keyframe. " +
            "For vector properties (location, rotation_euler, scale): a JSON array of 3 numbers. " +
            "For scalar properties (data.energy): a single number. " +
            "IMPORTANT: Arrays must be JSON arrays, NOT strings. " +
            "Example: [0, 0, 2.5] or 100.0.",
        },
      },
      required: ["name", "data_path"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/insert-keyframe", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_get_keyframes",
    description:
      "Retrieve all keyframes recorded on an object. " +
      "Optionally filter to a specific data path. " +
      "Returns: Array of { data_path, array_index, keyframe_points: [{ frame, value, interpolation }, ...] }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "The exact name of the object whose keyframes to retrieve. Example: \"Cube\".",
        },
        data_path: {
          type: "string",
          description:
            "If provided, only F-Curves matching this data path are returned. " +
            "Example: \"location\". Omit to return all F-Curves.",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/get-keyframes", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_set_frame",
    description:
      "Set the current frame of the active Blender scene. " +
      "Updates the timeline position and evaluates all animation data at that frame. " +
      "This is the primary/recommended tool for frame navigation. " +
      "Example call: { \"frame\": 24 }. " +
      "Returns: { success, frame }",
    inputSchema: {
      type: "object",
      properties: {
        frame: {
          type: "integer",
          description: "The frame number to jump to. Example: 24.",
        },
      },
      required: ["frame"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/set-frame", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
