// File tools — blender_file_info, blender_file_save, blender_file_open

import { sendToBlender } from "../../blender-bridge.js";

export const fileTools = [
  {
    name: "blender_file_info",
    description:
      "Get information about the current Blender file: filepath, save status, " +
      "Blender version, active scene, and object/mesh/material counts. " +
      "Returns: { filepath, is_saved, is_dirty, blender_version, active_scene, object_count, mesh_count, material_count }",
    inputSchema: {
      type: "object",
      properties: {},
    },
    handler: async () => {
      const result = await sendToBlender("file/info", {});
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_file_save",
    description:
      "Save the current Blender file. " +
      "If filepath is provided the file is saved to that path (Save As). " +
      "If no filepath is provided the file is saved in-place; the file must have been " +
      "saved at least once before, otherwise an error is returned. " +
      "Example call: { \"filepath\": \"C:/Projects/scene_v2.blend\", \"compress\": true }. " +
      "Returns: { success, filepath, compressed }",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description:
            "Destination path for the .blend file. " +
            "Example: \"C:/Projects/scene.blend\". Omit to save in-place.",
        },
        compress: {
          type: "boolean",
          description:
            "Write a compressed .blend file when true. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Defaults to false.",
        },
      },
    },
    handler: async (args) => {
      const result = await sendToBlender("file/save", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_file_open",
    description:
      "Open a .blend file in Blender. " +
      "WARNING: This reloads the entire Blender session — all unsaved changes will be lost. " +
      "Example call: { \"filepath\": \"C:/Projects/scene.blend\" }. " +
      "Returns: { success, filepath, active_scene, object_count }",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description: "Absolute path to the .blend file to open. Example: \"C:/Projects/scene.blend\".",
        },
      },
      required: ["filepath"],
    },
    handler: async (args) => {
      const result = await sendToBlender("file/open", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
