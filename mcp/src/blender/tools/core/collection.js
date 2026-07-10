// Collection tools — blender_collection_list, blender_collection_create

import { sendToBlender } from "../../blender-bridge.js";

export const collectionTools = [
  {
    name: "blender_collection_list",
    description:
      "List all collections in the current Blender file. " +
      "Returns: Array of { name, objects, children, color_tag, hide_viewport, hide_render }",
    inputSchema: {
      type: "object",
      properties: {},
    },
    handler: async () => {
      const result = await sendToBlender("collection/list", {});
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_collection_create",
    description:
      "Create a new collection in the Blender file and link it to a parent collection. " +
      "Example call: { \"name\": \"Props\", \"parent\": \"Scene Collection\", \"color_tag\": \"COLOR_02\" }. " +
      "Returns: { name, parent, color_tag }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "The name for the new collection. Example: \"Props\".",
        },
        parent: {
          type: "string",
          description:
            "Name of the parent collection to link into. " +
            "Example: \"Scene Collection\". Omit to link directly to the scene's master collection.",
        },
        color_tag: {
          type: "string",
          enum: ["NONE", "COLOR_01", "COLOR_02", "COLOR_03", "COLOR_04", "COLOR_05", "COLOR_06", "COLOR_07", "COLOR_08"],
          description:
            "Optional color tag for the collection. " +
            "Valid values: \"NONE\", \"COLOR_01\" through \"COLOR_08\". " +
            "Example: \"COLOR_02\".",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("collection/create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_collection_add_object",
    description:
      "Link an existing object to a collection. Optionally unlink from its current collection. " +
      "Example call: { \"collection_name\": \"Props\", \"object_name\": \"Microphone\" }. " +
      "Returns: { collection_name, object_name, success }",
    inputSchema: {
      type: "object",
      properties: {
        collection_name: {
          type: "string",
          description:
            "Name of the target collection. Example: \"Props\".",
        },
        object_name: {
          type: "string",
          description:
            "Name of the object to add. Example: \"Microphone\".",
        },
        unlink_current: {
          type: "boolean",
          description:
            "Unlink from current collection(s) before linking. " +
            "IMPORTANT: Must be JSON boolean. Defaults to false.",
        },
      },
      required: ["collection_name", "object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("collection/add-object", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_collection_delete",
    description:
      "Delete a collection from the Blender file. Objects in the collection are NOT deleted — " +
      "they remain in the scene. " +
      "Example call: { \"name\": \"Props\" }. " +
      "Returns: { name, objects_orphaned }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name of the collection to delete. Example: \"Props\".",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("collection/delete", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_collection_remove_object",
    description:
      "Remove (unlink) an object from a collection. The object remains in the scene " +
      "if it belongs to other collections. " +
      "Example call: { \"collection_name\": \"Props\", \"object_name\": \"Microphone\" }. " +
      "Returns: { collection_name, object_name }",
    inputSchema: {
      type: "object",
      properties: {
        collection_name: {
          type: "string",
          description: "Name of the collection to remove the object from. Example: \"Props\".",
        },
        object_name: {
          type: "string",
          description: "Name of the object to remove. Example: \"Microphone\".",
        },
      },
      required: ["collection_name", "object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("collection/remove-object", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_collection_set_visibility",
    description:
      "Toggle visibility properties of a collection (hide_viewport, hide_render). " +
      "Example call: { \"name\": \"Props\", \"hide_viewport\": true }. " +
      "Returns: { name, hide_viewport, hide_render }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name of the collection. Example: \"Props\".",
        },
        hide_viewport: {
          type: "boolean",
          description:
            "Hide/show collection in the viewport. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string.",
        },
        hide_render: {
          type: "boolean",
          description:
            "Hide/show collection in renders. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string.",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("collection/set-visibility", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
