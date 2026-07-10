// Scene tools — blender_scene_info, blender_scene_list, blender_scene_set_active

import { sendToBlender } from "../../blender-bridge.js";

export const sceneTools = [
  {
    name: "blender_scene_info",
    description:
      "Get information about the currently active Blender scene: name, object count, " +
      "frame range, current frame, render engine, and unit settings. " +
      "Returns: { name, object_count, frame_start, frame_end, frame_current, render_engine, unit_system, unit_scale }",
    inputSchema: {
      type: "object",
      properties: {},
    },
    handler: async () => {
      const result = await sendToBlender("scene/info", {});
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_scene_list",
    description:
      "List all scenes in the current Blender file. " +
      "Returns: Array of { name, object_count, is_active } for each scene.",
    inputSchema: {
      type: "object",
      properties: {},
    },
    handler: async () => {
      const result = await sendToBlender("scene/list", {});
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_scene_set_active",
    description:
      "Switch the active Blender scene to the scene with the given name. " +
      "Example call: { \"name\": \"Scene.001\" }. " +
      "Returns: { success, active_scene }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "The name of the scene to make active. Example: \"Scene\".",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("scene/set-active", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
