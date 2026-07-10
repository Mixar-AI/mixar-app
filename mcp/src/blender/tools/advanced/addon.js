// Advanced addon management tools — list, enable, disable, and configure Blender addons

import { sendToBlender } from "../../blender-bridge.js";

export const addonTools = [
  {
    name: "blender_addon_list",
    description:
      "List all installed Blender addons with their metadata. " +
      "Returns each addon's module name, display name, description, version, " +
      "category, and whether it is currently enabled. " +
      "The enabled status reflects the live preferences state. " +
      "Example call: {}.",
    inputSchema: {
      type: "object",
      properties: {},
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("addon/list", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_addon_enable",
    description:
      "Enable a Blender addon by its Python module name. " +
      "Equivalent to checking the addon in Blender's Preferences > Add-ons panel. " +
      "The addon must be installed; this only activates it for the current session. " +
      "Returns the module name and the resulting enabled state. " +
      "Example call: { \"module_name\": \"rigify\" }.",
    inputSchema: {
      type: "object",
      properties: {
        module_name: {
          type: "string",
          description:
            "Python module name of the addon to enable (e.g., 'rigify', 'io_scene_fbx', 'add_curve_extra_objects').",
        },
      },
      required: ["module_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("addon/enable", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_addon_disable",
    description:
      "Disable a currently-enabled Blender addon by its Python module name. " +
      "Equivalent to unchecking the addon in Blender's Preferences > Add-ons panel. " +
      "Returns the module name and the resulting enabled state. " +
      "Example call: { \"module_name\": \"io_scene_fbx\" }.",
    inputSchema: {
      type: "object",
      properties: {
        module_name: {
          type: "string",
          description:
            "Python module name of the addon to disable (e.g., 'rigify', 'io_scene_fbx').",
        },
      },
      required: ["module_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("addon/disable", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_addon_preferences",
    description:
      "Read or update preference properties of an enabled Blender addon. " +
      "If params is provided, each key/value pair is set on the addon's preferences object. " +
      "If params is omitted or empty, the current preference values are returned without modification. " +
      "The addon must be enabled and must expose an AddonPreferences class. " +
      "Returns the module name and a snapshot of all preference properties. " +
      "Example call: { \"module_name\": \"rigify\", \"params\": { \"export_format\": \"FBX\" } }.",
    inputSchema: {
      type: "object",
      properties: {
        module_name: {
          type: "string",
          description: "Python module name of the addon whose preferences to access.",
        },
        params: {
          type: "object",
          description:
            "Optional key/value pairs to set on the addon preferences. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Example: { \"export_format\": \"FBX\", \"debug_mode\": true }. " +
            "Omit to perform a read-only query of current preferences.",
        },
      },
      required: ["module_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("addon/preferences", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
