// Advanced vertex group tools — create, assign, remove, list, paint, and normalize vertex groups

import { sendToBlender } from "../../blender-bridge.js";

export const vertexGroupTools = [
  {
    name: "blender_vgroup_create",
    description:
      "Create a new empty vertex group on a mesh object. " +
      "If a vertex group with the given name already exists, the existing group is returned. " +
      "Returns the object name, vertex group name, and its index. " +
      "Example call: { \"object_name\": \"Cube\", \"group_name\": \"Top_Verts\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object.",
        },
        group_name: {
          type: "string",
          description: "Name for the new vertex group.",
        },
      },
      required: ["object_name", "group_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("vgroup/create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_vgroup_assign",
    description:
      "Assign a weight value to a set of vertices in a named vertex group. " +
      "The vertex group must already exist on the object. " +
      "Uses REPLACE mode, overwriting any existing weight for each listed vertex. " +
      "Returns the object name, group name, number of vertices assigned, and the weight. " +
      "Example call: { \"object_name\": \"Cube\", \"group_name\": \"Top_Verts\", \"vertex_indices\": [0, 1, 2, 3], \"weight\": 1.0 }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object.",
        },
        group_name: {
          type: "string",
          description: "Name of the target vertex group.",
        },
        vertex_indices: {
          type: "array",
          items: { type: "integer" },
          description:
            "Array of vertex indices to assign weights to. " +
            "IMPORTANT: Must be a JSON array of integers, NOT a string. " +
            "Example: [0, 1, 2, 15, 16].",
        },
        weight: {
          type: "number",
          description: "Weight value to assign, in the range 0.0 (no influence) to 1.0 (full influence).",
        },
      },
      required: ["object_name", "group_name", "vertex_indices", "weight"],
    },
    handler: async (args) => {
      const result = await sendToBlender("vgroup/assign", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_vgroup_remove",
    description:
      "Remove a vertex group from a mesh object. " +
      "All vertex weight data stored in the group is deleted permanently. " +
      "Returns the object name and the removed group name.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object.",
        },
        group_name: {
          type: "string",
          description: "Name of the vertex group to remove.",
        },
      },
      required: ["object_name", "group_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("vgroup/remove", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_vgroup_list",
    description:
      "List all vertex groups on a mesh object. " +
      "Returns each group's name, index within the vertex_groups collection, " +
      "and whether its weight values are locked.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("vgroup/list", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_vgroup_paint",
    description:
      "Procedurally paint vertex weights onto a mesh using a gradient pattern. " +
      "TOP_BOTTOM assigns weight 1.0 at the topmost vertices (highest Z) and 0.0 at the bottom. " +
      "CENTER_OUT assigns weight 1.0 at the mesh center and 0.0 at the farthest vertices. " +
      "The vertex group is created if it does not already exist. " +
      "Returns the object name, group name, gradient type, and number of vertices painted.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object.",
        },
        group_name: {
          type: "string",
          description: "Name of the vertex group to paint into.",
        },
        gradient: {
          type: "string",
          enum: ["TOP_BOTTOM", "CENTER_OUT"],
          description:
            "Gradient pattern. Must be UPPERCASE. TOP_BOTTOM: high Z = weight 1.0, low Z = weight 0.0. " +
            "CENTER_OUT: mesh center = weight 1.0, outer edges = weight 0.0. " +
            "Defaults to TOP_BOTTOM.",
        },
      },
      required: ["object_name", "group_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("vgroup/paint", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_vgroup_normalize",
    description:
      "Normalize all vertex group weights on a mesh so that the total weight per vertex sums to 1.0. " +
      "Uses Blender's built-in vertex_group_normalize_all operator. " +
      "Returns the object name and the number of vertex groups present.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object whose weights to normalize.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("vgroup/normalize", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
