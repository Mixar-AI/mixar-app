// Advanced modeling tools — mesh from data, edit ops, select, separate, merge, normals

import { sendToBlender } from "../../blender-bridge.js";

export const modelingTools = [
  {
    name: "blender_mesh_from_data",
    description:
      "Create a new mesh object from raw vertex and face data. " +
      "Example call: { \"name\": \"Triangle\", \"vertices\": [[0,0,0], [1,0,0], [0.5,1,0]], \"faces\": [[0,1,2]] }. " +
      "Returns the new object name and mesh statistics.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name for the new mesh object. Example: \"CustomMesh\".",
        },
        vertices: {
          type: "array",
          items: {
            type: "array",
            items: { type: "number" },
            minItems: 3,
            maxItems: 3,
          },
          description:
            "List of vertex positions, each as a JSON array of 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of arrays, NOT a string. " +
            "Example: [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]].",
        },
        faces: {
          type: "array",
          items: {
            type: "array",
            items: { type: "integer" },
          },
          description:
            "List of faces, each as a JSON array of vertex indices (0-based). " +
            "IMPORTANT: Must be a JSON array of arrays, NOT a string. " +
            "Example: [[0, 1, 2, 3]] (one quad) or [[0, 1, 2], [0, 2, 3]] (two triangles).",
        },
        edges: {
          type: "array",
          items: {
            type: "array",
            items: { type: "integer" },
            minItems: 2,
            maxItems: 2,
          },
          description:
            "Optional explicit edge pairs as JSON arrays of 2 vertex indices. " +
            "Example: [[0, 1], [1, 2]].",
        },
      },
      required: ["name", "vertices", "faces"],
    },
    handler: async (args) => {
      const result = await sendToBlender("mesh/from-data", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_mesh_edit",
    description:
      "Perform a mesh edit operation on an existing mesh object. " +
      "Supported operations: EXTRUDE, INSET, BEVEL, LOOP_CUT, SUBDIVIDE, DISSOLVE, MOVE. " +
      "Example call: { \"object_name\": \"Cube\", \"operation\": \"EXTRUDE\", \"parameters\": { \"value\": 0.5 } }. " +
      "Returns the operation result.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to edit. Example: \"Cube\".",
        },
        operation: {
          type: "string",
          enum: ["EXTRUDE", "INSET", "BEVEL", "LOOP_CUT", "SUBDIVIDE", "DISSOLVE", "MOVE"],
          description: "The mesh edit operation to perform. Must be UPPERCASE. Example: \"EXTRUDE\".",
        },
        parameters: {
          type: "object",
          description:
            "Operation-specific parameters as a JSON object. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "EXTRUDE: { \"value\": 0.5 } (Z translation distance). " +
            "INSET: { \"thickness\": 0.02, \"depth\": 0 }. " +
            "BEVEL: { \"offset\": 0.1, \"segments\": 2 }. " +
            "LOOP_CUT: { \"cuts\": 3, \"edge_index\": 0 }. " +
            "SUBDIVIDE: { \"cuts\": 2 }. " +
            "DISSOLVE: { \"angle\": 5.0 } (max angle in degrees). " +
            "MOVE: { \"value\": [x, y, z] } — translation vector applied to selected elements. IMPORTANT: value must be a JSON array of 3 numbers.",
        },
      },
      required: ["object_name", "operation"],
    },
    handler: async (args) => {
      const result = await sendToBlender("mesh/edit", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_mesh_select",
    description:
      "Select mesh elements on an object in Edit Mode. " +
      "Supports: ALL, NONE, FACE_INDEX, VERT_INDEX, EDGE_INDEX, TOP, BOTTOM, LOOP, LINKED, BY_NORMAL. " +
      "Example call: { \"object_name\": \"Cube\", \"mode\": \"TOP\", \"parameters\": { \"threshold\": 0.9 } }. " +
      "The object remains in Edit Mode after the operation.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object. Example: \"Cube\".",
        },
        mode: {
          type: "string",
          enum: [
            "ALL", "NONE", "FACE_INDEX", "VERT_INDEX", "EDGE_INDEX",
            "TOP", "BOTTOM", "LOOP", "LINKED", "BY_NORMAL",
          ],
          description: "Selection mode. Must be UPPERCASE. Example: \"TOP\".",
        },
        parameters: {
          type: "object",
          description:
            "Mode-specific parameters as a JSON object. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "FACE_INDEX/VERT_INDEX/EDGE_INDEX: { \"indices\": [0, 1, 5] } (array of integers). " +
            "TOP/BOTTOM: { \"threshold\": 0.9 } (normal Z threshold). " +
            "LOOP: { \"edge_index\": 4 }. " +
            "BY_NORMAL: { \"direction\": [0, 0, 1], \"threshold\": 0.9 }.",
        },
      },
      required: ["object_name", "mode"],
    },
    handler: async (args) => {
      const result = await sendToBlender("mesh/select", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_mesh_separate",
    description:
      "Separate a mesh object into multiple objects. " +
      "SELECTED: separate selected geometry. MATERIAL: separate by material slot. LOOSE: separate by disconnected islands. " +
      "Example call: { \"object_name\": \"Combined\", \"mode\": \"MATERIAL\" }. " +
      "Returns the names of all resulting objects.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to separate. Example: \"Combined\".",
        },
        mode: {
          type: "string",
          enum: ["SELECTED", "MATERIAL", "LOOSE"],
          description: "Separation mode. Must be UPPERCASE. Example: \"MATERIAL\".",
        },
      },
      required: ["object_name", "mode"],
    },
    handler: async (args) => {
      const result = await sendToBlender("mesh/separate", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_mesh_merge",
    description:
      "Merge vertices on a mesh object. BY_DISTANCE removes duplicates within a threshold. " +
      "CENTER/CURSOR/COLLAPSE merge selected vertices to a point. " +
      "Example call: { \"object_name\": \"Cube\", \"mode\": \"BY_DISTANCE\", \"threshold\": 0.001 }. " +
      "Returns the number of vertices removed.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object. Example: \"Cube\".",
        },
        mode: {
          type: "string",
          enum: ["BY_DISTANCE", "CENTER", "CURSOR", "COLLAPSE"],
          description: "Merge mode. Must be UPPERCASE. Example: \"BY_DISTANCE\".",
        },
        threshold: {
          type: "number",
          description: "Distance threshold for BY_DISTANCE mode. Example: 0.001. Defaults to 0.0001.",
        },
      },
      required: ["object_name", "mode"],
    },
    handler: async (args) => {
      const result = await sendToBlender("mesh/merge", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_mesh_normals",
    description:
      "Perform normals operations on a mesh object. " +
      "SMOOTH/FLAT: set shading. AUTO_SMOOTH: angle-based smooth. RECALCULATE: fix outward. FLIP: reverse all. " +
      "Example call: { \"object_name\": \"Sphere\", \"mode\": \"AUTO_SMOOTH\", \"auto_smooth_angle\": 30 }. " +
      "Returns the operation performed and the object name.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object. Example: \"Sphere\".",
        },
        mode: {
          type: "string",
          enum: ["SMOOTH", "FLAT", "AUTO_SMOOTH", "RECALCULATE", "FLIP"],
          description: "Normals operation mode. Must be UPPERCASE. Example: \"AUTO_SMOOTH\".",
        },
        auto_smooth_angle: {
          type: "number",
          description:
            "Angle threshold in degrees for AUTO_SMOOTH mode. Example: 30. Defaults to 30.",
        },
      },
      required: ["object_name", "mode"],
    },
    handler: async (args) => {
      const result = await sendToBlender("mesh/normals", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_boolean_operation",
    description:
      "Perform a Boolean operation between two mesh objects. " +
      "Creates a Boolean modifier on the target, sets the cutter object, applies the modifier, and optionally removes the cutter. " +
      "Example call: { \"object_name\": \"Axe_Head\", \"cutter\": \"Cut_Shape\", \"operation\": \"DIFFERENCE\", \"apply\": true, \"remove_cutter\": true }. " +
      "Returns: { object_name, operation, vertex_count, face_count }",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the target mesh object. Example: \"Axe_Head\".",
        },
        cutter: {
          type: "string",
          description: "Name of the cutter mesh object. Example: \"Cut_Shape\".",
        },
        operation: {
          type: "string",
          enum: ["DIFFERENCE", "UNION", "INTERSECT"],
          description: "Boolean operation type. Must be UPPERCASE. Example: \"DIFFERENCE\".",
        },
        apply: {
          type: "boolean",
          description: "Apply the modifier immediately when true. IMPORTANT: Must be a JSON boolean. Defaults to true.",
        },
        remove_cutter: {
          type: "boolean",
          description: "Delete the cutter object after applying when true. IMPORTANT: Must be a JSON boolean. Defaults to false.",
        },
      },
      required: ["object_name", "cutter", "operation"],
    },
    handler: async (args) => {
      const result = await sendToBlender("mesh/boolean", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
