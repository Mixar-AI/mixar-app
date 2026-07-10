// Object tools — blender_object_list, blender_object_info, blender_object_create,
//                blender_object_delete, blender_object_transform,
//                blender_object_duplicate, blender_object_select, blender_object_join,
//                blender_object_set_parent, blender_object_apply_transforms

import { sendToBlender } from "../../blender-bridge.js";

export const objectTools = [
  {
    name: "blender_object_list",
    description:
      "List objects in the current Blender scene with pagination. " +
      "Optionally filter by object type (e.g. MESH, LIGHT, CAMERA, CURVE, EMPTY). " +
      "Returns: { objects: [{ name, type, location, visible }], total_count, limit, offset }",
    inputSchema: {
      type: "object",
      properties: {
        type: {
          type: "string",
          enum: ["MESH", "LIGHT", "CAMERA", "CURVE", "EMPTY", "ARMATURE", "LATTICE", "FONT", "SPEAKER"],
          description:
            "Filter results to this object type. Must be UPPERCASE. " +
            "Valid values: MESH, LIGHT, CAMERA, CURVE, EMPTY, ARMATURE, LATTICE, FONT, SPEAKER. " +
            "Example: \"MESH\". Omit to return all objects.",
        },
        limit: {
          type: "integer",
          description:
            "Maximum number of objects to return. Default 500, max 5000. " +
            "Use with offset for pagination in large scenes.",
        },
        offset: {
          type: "integer",
          description:
            "Number of objects to skip before returning results. Default 0. " +
            "Use with limit for pagination.",
        },
      },
    },
    handler: async (args) => {
      const result = await sendToBlender("object/list", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_object_info",
    description:
      "Get detailed information about a specific object: type, transform, dimensions, " +
      "parent, collections, modifiers, materials, and mesh statistics (if applicable). " +
      "Returns: { name, type, location, rotation, scale, dimensions, parent, collections, modifiers, materials, mesh_stats }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "The exact name of the object in Blender. Example: \"Cube\".",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("object/info", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_object_create",
    description:
      "Create a new object (mesh primitive or empty) in the current Blender scene. " +
      "Supported types: CUBE, SPHERE, CYLINDER, PLANE, CONE, TORUS, EMPTY (and CIRCLE, GRID, MONKEY). " +
      "Example call: { \"type\": \"CUBE\", \"name\": \"MyCube\", \"location\": [1.0, 2.0, 0.0], \"scale\": [1, 1, 2] }. " +
      "Returns: { name, type, location }",
    inputSchema: {
      type: "object",
      properties: {
        type: {
          type: "string",
          enum: ["CUBE", "SPHERE", "CYLINDER", "PLANE", "CONE", "TORUS", "CIRCLE", "GRID", "MONKEY", "EMPTY"],
          description:
            "The kind of object to create. Must be UPPERCASE. " +
            "Valid values: CUBE, SPHERE, CYLINDER, PLANE, CONE, TORUS, CIRCLE, GRID, MONKEY, EMPTY. " +
            "Example: \"CYLINDER\".",
        },
        name: {
          type: "string",
          description: "Optional name for the new object. Example: \"Table_Leg\".",
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "World-space position as a JSON array of exactly 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [1.0, 2.5, 0.0]. Defaults to [0, 0, 0].",
        },
        rotation: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Euler rotation as a JSON array of exactly 3 numbers [x, y, z] in RADIANS. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [0, 0, 1.5708] (90 degrees around Z). Defaults to [0, 0, 0].",
        },
        scale: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Scale factors as a JSON array of exactly 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [1, 1, 2] (doubled height). Defaults to [1, 1, 1].",
        },
      },
      required: ["type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("object/create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_object_delete",
    description:
      "Delete one or more objects from the current Blender scene. " +
      "Provide either a single object name or an array of names. " +
      "Example: { \"names\": [\"Cube\", \"Cube.001\"] } or { \"name\": \"Cube\" }. " +
      "Returns: { deleted_count, deleted_names }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name of a single object to delete. Example: \"Cube\".",
        },
        names: {
          type: "array",
          items: { type: "string" },
          description:
            "JSON array of object name strings to delete. " +
            "IMPORTANT: Must be a JSON array of strings, NOT a string. " +
            "Example: [\"Cube\", \"Sphere\", \"Cylinder\"].",
        },
      },
    },
    handler: async (args) => {
      const result = await sendToBlender("object/delete", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_object_transform",
    description:
      "Set the location, rotation, and/or scale of an existing object. " +
      "Only the provided transform components are updated; omitted ones are left unchanged. " +
      "Example call: { \"name\": \"Cube\", \"location\": [0, 0, 1.5], \"scale\": [2, 2, 0.1] }. " +
      "Returns: { name, location, rotation, scale }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "The exact name of the object to transform. Example: \"Cube\".",
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "New world-space position as a JSON array of exactly 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Correct: [1.0, 2.0, 0.5] — Wrong: \"[1.0, 2.0, 0.5]\".",
        },
        rotation: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "New Euler rotation as a JSON array of exactly 3 numbers [x, y, z] in RADIANS. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [0, 0, 0.7854] (45° around Z). Use Math.PI/2 = 1.5708 for 90°.",
        },
        scale: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "New scale factors as a JSON array of exactly 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [2, 2, 0.5] (wide and flat).",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("object/transform", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_object_duplicate",
    description:
      "Duplicate an existing object. By default creates a full copy with its own mesh data. " +
      "Set linked to true (JSON boolean) to create an instance that shares the original's mesh data. " +
      "Example call: { \"name\": \"Cube\", \"new_name\": \"Cube_Copy\", \"linked\": false }. " +
      "Returns: { name, original, linked }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "The exact name of the object to duplicate. Example: \"Table\".",
        },
        new_name: {
          type: "string",
          description: "Optional name for the duplicated object. Example: \"Table_Copy\".",
        },
        linked: {
          type: "boolean",
          description:
            "If true, the duplicate shares mesh data with the original (linked/instance). " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Correct: true — Wrong: \"true\". Defaults to false.",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("object/duplicate", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_object_select",
    description:
      "Select or deselect objects in the scene. Supports SET (replace selection), " +
      "ADD (extend), REMOVE (deselect), and TOGGLE modes. " +
      "Example call: { \"names\": [\"Cube\", \"Sphere\"], \"mode\": \"SET\" }. " +
      "Returns: { selected, active }",
    inputSchema: {
      type: "object",
      properties: {
        names: {
          type: "array",
          items: { type: "string" },
          description:
            "JSON array of object name strings to act on. " +
            "IMPORTANT: Must be a JSON array of strings, NOT a string. " +
            "Example: [\"Cube\", \"Sphere\"].",
        },
        mode: {
          type: "string",
          enum: ["SET", "ADD", "REMOVE", "TOGGLE"],
          description:
            "Selection mode. Must be UPPERCASE. " +
            "SET: replaces current selection, ADD: extends it, REMOVE: deselects, TOGGLE: flips state. " +
            "Example: \"SET\". Defaults to \"SET\".",
        },
        active: {
          type: "string",
          description:
            "Name of the object to set as active (highlighted) after selection. Example: \"Cube\".",
        },
      },
      required: ["names"],
    },
    handler: async (args) => {
      const result = await sendToBlender("object/select", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_object_join",
    description:
      "Join multiple mesh objects into a single object. All source meshes are merged into the target. " +
      "Example call: { \"names\": [\"Head\", \"Handle\", \"Guard\"] }. " +
      "The \"names\" parameter IMPORTANT: Must be a JSON array of strings. " +
      "Returns: { object_name, name, vertex_count, face_count, material_count, joined_count }",
    inputSchema: {
      type: "object",
      properties: {
        names: {
          type: "array",
          items: { type: "string" },
          description:
            "Array of object names to join. " +
            "IMPORTANT: Must be a JSON array of strings, NOT a string. " +
            "Example: [\"Head\", \"Handle\", \"Guard\"].",
        },
        target_name: {
          type: "string",
          description:
            "Optional. Name of the object that others merge into. " +
            "Defaults to the first object in the names array.",
        },
      },
      required: ["names"],
    },
    handler: async (args) => {
      const result = await sendToBlender("object/join", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_object_set_parent",
    description:
      "Set or clear an object's parent. " +
      "Example call: { \"child\": \"Axe_Head\", \"parent\": \"Axe_Root\", \"keep_transform\": true }. " +
      "Pass empty string for parent to unparent (clear parent). " +
      "Returns: { object_name, name, parent, world_location }",
    inputSchema: {
      type: "object",
      properties: {
        child: {
          type: "string",
          description: "Name of the child object.",
        },
        parent: {
          type: "string",
          description:
            "Name of the parent object. Pass empty string to clear parent (unparent).",
        },
        keep_transform: {
          type: "boolean",
          description:
            "If true, child keeps its world transform. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Correct: true — Wrong: \"true\". Default: true.",
        },
      },
      required: ["child", "parent"],
    },
    handler: async (args) => {
      const result = await sendToBlender("object/set-parent", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_object_apply_transforms",
    description:
      "Apply (freeze) an object's location, rotation, and/or scale so the transform " +
      "values reset to identity while the mesh keeps its current shape. " +
      "Example call: { \"name\": \"Cube\", \"location\": true, \"rotation\": true, \"scale\": false }. " +
      "Returns: { object_name, applied, location, rotation, scale }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "The exact name of the object to apply transforms on. Example: \"Cube\".",
        },
        location: {
          type: "boolean",
          description:
            "Whether to apply (freeze) the location transform. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Correct: true — Wrong: \"true\". Defaults to true.",
        },
        rotation: {
          type: "boolean",
          description:
            "Whether to apply (freeze) the rotation transform. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Correct: true — Wrong: \"true\". Defaults to true.",
        },
        scale: {
          type: "boolean",
          description:
            "Whether to apply (freeze) the scale transform. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Correct: true — Wrong: \"true\". Defaults to true.",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("object/apply-transforms", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
