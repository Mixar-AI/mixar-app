// Modifier tools — blender_modifier_list, blender_modifier_add,
//   blender_modifier_remove, blender_modifier_set_property, blender_modifier_apply

import { sendToBlender } from "../../blender-bridge.js";

export const modifierTools = [
  {
    name: "blender_modifier_list",
    description:
      "List all modifiers on a Blender object. " +
      "Returns: Array of { name, type, show_viewport, show_render }",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object whose modifiers to list. Example: \"Cube\".",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("modifier/list", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_modifier_add",
    description:
      "Add a modifier to a Blender object. Supported types include: SUBSURF, MIRROR, " +
      "ARRAY, BOOLEAN, SOLIDIFY, BEVEL, SHRINKWRAP, DISPLACE, DECIMATE, REMESH, " +
      "SCREW, SKIN, WELD, WIREFRAME, and more. " +
      "Example call: { \"object_name\": \"Cube\", \"type\": \"SUBSURF\", \"properties\": { \"levels\": 2, \"render_levels\": 3 } }. " +
      "Returns: { object_name, modifier_name, type }",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object to add the modifier to. Example: \"Cube\".",
        },
        type: {
          type: "string",
          description:
            "Modifier type identifier. Must be UPPERCASE. " +
            "Common values: \"SUBSURF\", \"MIRROR\", \"ARRAY\", \"SOLIDIFY\", \"BEVEL\", " +
            "\"BOOLEAN\", \"DECIMATE\", \"REMESH\", \"SCREW\", \"WIREFRAME\". " +
            "Example: \"SUBSURF\".",
        },
        name: {
          type: "string",
          description: "Optional custom name for the modifier. Example: \"MySubdivision\".",
        },
        properties: {
          type: "object",
          description:
            "Optional JSON object of modifier property names and values to set after creation. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Example: { \"levels\": 2, \"use_x\": true, \"use_y\": false }.",
        },
      },
      required: ["object_name", "type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("modifier/add", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_modifier_remove",
    description:
      "Remove a named modifier from a Blender object. " +
      "Example call: { \"object_name\": \"Cube\", \"modifier_name\": \"Subdivision\" }. " +
      "Returns: { success, object_name, modifier_name }",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the modifier. Example: \"Cube\".",
        },
        modifier_name: {
          type: "string",
          description: "Name of the modifier to remove. Example: \"Subdivision\".",
        },
      },
      required: ["object_name", "modifier_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("modifier/remove", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_modifier_set_property",
    description:
      "Set a single property on an existing modifier. " +
      "Use Python attribute names (e.g. 'levels', 'render_levels', 'use_x', 'count'). " +
      "Example call: { \"object_name\": \"Cube\", \"modifier_name\": \"Array\", \"property\": \"count\", \"value\": 5 }. " +
      "Returns: { object_name, modifier_name, property, value }",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the modifier. Example: \"Cube\".",
        },
        modifier_name: {
          type: "string",
          description: "Name of the modifier to modify. Example: \"Array\".",
        },
        property: {
          type: "string",
          description:
            "Python attribute name of the modifier property to set. " +
            "Examples: \"levels\", \"render_levels\", \"count\", \"use_x\", \"offset\".",
        },
        value: {
          oneOf: [
            { type: "number" },
            { type: "boolean" },
            { type: "string" },
          ],
          description:
            "New value for the property. Can be a number, boolean, or string. " +
            "IMPORTANT: Booleans must be JSON booleans (true/false), NOT strings. " +
            "Correct: true — Wrong: \"true\". " +
            "Examples: 3 (integer), 0.5 (float), true (boolean), \"CTRL_1\" (enum string).",
        },
      },
      required: ["object_name", "modifier_name", "property", "value"],
    },
    handler: async (args) => {
      const result = await sendToBlender("modifier/set-property", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_modifier_apply",
    description:
      "Apply (collapse) a modifier on a Blender object, permanently baking it into the mesh. " +
      "The object must be a mesh and the modifier must exist. " +
      "Example call: { \"object_name\": \"Cube\", \"modifier_name\": \"Subdivision\" }. " +
      "Returns: { success, object_name, modifier_name }",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the modifier. Example: \"Cube\".",
        },
        modifier_name: {
          type: "string",
          description: "Name of the modifier to apply. Example: \"Subdivision\".",
        },
      },
      required: ["object_name", "modifier_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("modifier/apply", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
