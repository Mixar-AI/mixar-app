// Advanced curve tools — create, edit points, set properties, convert, bevel/taper objects

import { sendToBlender } from "../../blender-bridge.js";

export const curveTools = [
  {
    name: "blender_curve_create",
    description:
      "Create a new curve object in the scene. " +
      "Supports BEZIER, NURBS, and PATH spline types. " +
      "Optionally supply an array of [x, y, z] control points to populate the spline immediately. " +
      "Example call: { \"type\": \"BEZIER\", \"name\": \"MyCurve\", \"points\": [[0,0,0], [1,0,1], [2,0,0]] }. " +
      "Returns the new object name and spline type.",
    inputSchema: {
      type: "object",
      properties: {
        type: {
          type: "string",
          enum: ["BEZIER", "NURBS", "PATH"],
          description: "Spline type to create. Must be UPPERCASE.",
        },
        name: {
          type: "string",
          description: "Name for the new curve object.",
        },
        points: {
          type: "array",
          items: {
            type: "array",
            items: { type: "number" },
            minItems: 3,
            maxItems: 3,
          },
          description:
            "Optional list of [x, y, z] control point positions. " +
            "IMPORTANT: Must be a JSON array of arrays, NOT a string. " +
            "Example: [[0, 0, 0], [1, 0, 1], [2, 0, 0]].",
        },
      },
      required: ["type", "name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("curve/create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_curve_add_point",
    description:
      "Append a new control point to the first spline of an existing curve object. " +
      "For BEZIER splines, optional handle positions can be supplied. " +
      "Returns the updated point count.",
    inputSchema: {
      type: "object",
      properties: {
        curve_name: {
          type: "string",
          description: "Name of the curve object.",
        },
        position: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Position [x, y, z] of the new control point. " +
            "IMPORTANT: Must be a JSON array of 3 numbers, NOT a string. Example: [1.0, 0, 0.5].",
        },
        handle_left: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Left handle position [x, y, z] for BEZIER splines. " +
            "IMPORTANT: Must be a JSON array of 3 numbers, NOT a string. Example: [0.5, 0, 0].",
        },
        handle_right: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Right handle position [x, y, z] for BEZIER splines. " +
            "IMPORTANT: Must be a JSON array of 3 numbers, NOT a string. Example: [1.5, 0, 0].",
        },
      },
      required: ["curve_name", "position"],
    },
    handler: async (args) => {
      const result = await sendToBlender("curve/add-point", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_curve_edit_point",
    description:
      "Edit an existing control point on the first spline of a curve object by index. " +
      "Supports moving the point, adjusting handles (BEZIER), and setting tilt. " +
      "Returns the updated point data.",
    inputSchema: {
      type: "object",
      properties: {
        curve_name: {
          type: "string",
          description: "Name of the curve object.",
        },
        index: {
          type: "integer",
          description: "Zero-based index of the control point to edit.",
        },
        position: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "New position [x, y, z] for the control point. " +
            "IMPORTANT: Must be a JSON array of 3 numbers, NOT a string. Example: [1.0, 0.5, 0].",
        },
        handle_left: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "New left handle position [x, y, z] (BEZIER only). " +
            "IMPORTANT: Must be a JSON array of 3 numbers, NOT a string.",
        },
        handle_right: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "New right handle position [x, y, z] (BEZIER only). " +
            "IMPORTANT: Must be a JSON array of 3 numbers, NOT a string.",
        },
        tilt: {
          type: "number",
          description: "Tilt angle in radians (BEZIER only).",
        },
      },
      required: ["curve_name", "index"],
    },
    handler: async (args) => {
      const result = await sendToBlender("curve/edit-point", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_curve_set_properties",
    description:
      "Set render and geometry properties on a curve object. " +
      "Controls preview/render resolution, bevel depth and resolution, extrude amount, " +
      "and twist interpolation mode. Returns the updated property values.",
    inputSchema: {
      type: "object",
      properties: {
        curve_name: {
          type: "string",
          description: "Name of the curve object.",
        },
        resolution: {
          type: "integer",
          maximum: 1024,
          description: "Preview resolution (resolution_u) — number of subdivisions per segment.",
        },
        bevel_depth: {
          type: "number",
          description: "Bevel depth — radius of the bevel cross-section.",
        },
        bevel_resolution: {
          type: "integer",
          description: "Number of vertices in the bevel cross-section circle.",
        },
        extrude: {
          type: "number",
          description: "Extrude amount — extends the curve along its normal.",
        },
        twist_mode: {
          type: "string",
          enum: ["Z_UP", "MINIMUM", "TANGENT"],
          description: "Twist interpolation mode along the curve. Must be UPPERCASE.",
        },
      },
      required: ["curve_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("curve/set-properties", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_curve_to_mesh",
    description:
      "Convert a curve object to a mesh object in-place using the current bevel/extrude settings. " +
      "Optionally specify a profile curve to use as the bevel shape before conversion. " +
      "Returns the resulting object name and mesh statistics.",
    inputSchema: {
      type: "object",
      properties: {
        curve_name: {
          type: "string",
          description: "Name of the curve object to convert.",
        },
        profile_curve: {
          type: "string",
          description: "Optional name of a curve object to use as the bevel profile before conversion.",
        },
      },
      required: ["curve_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("curve/to-mesh", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_curve_from_points",
    description:
      "Create a curve object by providing a complete ordered list of [x, y, z] points in one call. " +
      "Supports BEZIER, NURBS, and POLY spline types. " +
      "Optionally close the spline into a loop with the cyclic flag. " +
      "Returns the new object name and point count.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name for the new curve object.",
        },
        points: {
          type: "array",
          items: {
            type: "array",
            items: { type: "number" },
            minItems: 3,
            maxItems: 3,
          },
          description:
            "Ordered list of [x, y, z] control point positions. " +
            "IMPORTANT: Must be a JSON array of arrays, NOT a string. " +
            "Example: [[0, 0, 0], [1, 1, 0], [2, 0, 0]].",
        },
        type: {
          type: "string",
          enum: ["BEZIER", "NURBS", "POLY"],
          description: "Spline type. Must be UPPERCASE. Defaults to BEZIER.",
        },
        cyclic: {
          type: "boolean",
          description:
            "Whether to close the spline into a loop. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Defaults to false.",
        },
      },
      required: ["name", "points"],
    },
    handler: async (args) => {
      const result = await sendToBlender("curve/from-points", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_curve_set_bevel_object",
    description:
      "Assign a curve object as the bevel (cross-section profile) object for another curve. " +
      "The bevel object defines the shape extruded along the path curve. " +
      "Returns the curve name and the assigned bevel object name.",
    inputSchema: {
      type: "object",
      properties: {
        curve_name: {
          type: "string",
          description: "Name of the path curve to receive the bevel object.",
        },
        bevel_object_name: {
          type: "string",
          description: "Name of the curve object to use as the bevel profile.",
        },
      },
      required: ["curve_name", "bevel_object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("curve/set-bevel-object", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_curve_set_taper_object",
    description:
      "Assign a curve object as the taper object for another curve. " +
      "The taper curve controls how the cross-section scales along the path. " +
      "Returns the curve name and the assigned taper object name.",
    inputSchema: {
      type: "object",
      properties: {
        curve_name: {
          type: "string",
          description: "Name of the path curve to receive the taper object.",
        },
        taper_object_name: {
          type: "string",
          description: "Name of the curve object to use as the taper profile.",
        },
      },
      required: ["curve_name", "taper_object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("curve/set-taper-object", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
