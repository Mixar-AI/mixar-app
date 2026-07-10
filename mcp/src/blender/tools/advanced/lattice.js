// Advanced lattice tools — lattice object creation, assignment, point editing, and fitting

import { sendToBlender } from "../../blender-bridge.js";

export const latticeTools = [
  {
    name: "blender_lattice_create",
    description:
      "Create a new lattice object in the scene. " +
      "A lattice data block is created with the specified resolution (control point counts " +
      "along U, V, and W axes) and linked to the active collection at the given location. " +
      "Returns the lattice object name, location, and resolution. " +
      "Example call: { \"name\": \"Deformer\", \"location\": [0, 0, 0], \"resolution\": [4, 4, 4] }.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name for the new lattice object.",
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "World-space location [x, y, z] for the lattice. " +
            "IMPORTANT: Must be a JSON array of 3 numbers, NOT a string. " +
            "Example: [0, 0, 0]. Defaults to [0, 0, 0].",
        },
        resolution: {
          type: "object",
          description:
            "Control point resolution along each axis. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Example: { \"u\": 4, \"v\": 4, \"w\": 4 }. Defaults to { \"u\": 2, \"v\": 2, \"w\": 2 }.",
          properties: {
            u: { type: "integer", description: "Control points along the U axis (minimum 2)." },
            v: { type: "integer", description: "Control points along the V axis (minimum 2)." },
            w: { type: "integer", description: "Control points along the W axis (minimum 2)." },
          },
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("lattice/create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_lattice_assign",
    description:
      "Assign a lattice deformer to a target object by adding a Lattice modifier. " +
      "The modifier is appended to the target object's modifier stack and its object " +
      "reference is set to the named lattice. " +
      "Returns the lattice name, target object name, and modifier name.",
    inputSchema: {
      type: "object",
      properties: {
        lattice_name: {
          type: "string",
          description: "Name of the lattice object to use as the deformer.",
        },
        object_name: {
          type: "string",
          description: "Name of the target object to receive the Lattice modifier.",
        },
      },
      required: ["lattice_name", "object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("lattice/assign", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_lattice_edit_point",
    description:
      "Move a single control point of a lattice to a new position. " +
      "The point is identified by its flat index into the lattice point array. " +
      "The position is applied via co_deform, which works in Object Mode without " +
      "requiring an Edit Mode context switch. " +
      "Returns the lattice name, point index, and new position.",
    inputSchema: {
      type: "object",
      properties: {
        lattice_name: {
          type: "string",
          description: "Name of the lattice object.",
        },
        index: {
          type: "integer",
          description:
            "Flat index of the control point to move. " +
            "Points are ordered W-major, then V, then U (innermost).",
        },
        position: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "New position [x, y, z] in lattice local space. " +
            "IMPORTANT: Must be a JSON array of 3 numbers, NOT a string. " +
            "Example: [0.5, 0, 0.5].",
        },
      },
      required: ["lattice_name", "index", "position"],
    },
    handler: async (args) => {
      const result = await sendToBlender("lattice/edit-point", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_lattice_fit_to_object",
    description:
      "Resize and reposition a lattice to exactly enclose a target object's bounding box. " +
      "The lattice is moved to the world-space center of the target's bounding box and " +
      "scaled to match its dimensions, with an optional uniform margin applied on all sides. " +
      "Returns the lattice name, target object name, computed center, and final scale.",
    inputSchema: {
      type: "object",
      properties: {
        lattice_name: {
          type: "string",
          description: "Name of the lattice object to reposition.",
        },
        object_name: {
          type: "string",
          description: "Name of the target object whose bounding box will be used.",
        },
        margin: {
          type: "number",
          description:
            "Uniform padding in Blender units added to each side of the bounding box. Defaults to 0.0.",
        },
      },
      required: ["lattice_name", "object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("lattice/fit-to-object", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
