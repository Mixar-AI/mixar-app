// Advanced Grease Pencil tools — create GP objects, layers, strokes, materials, modifiers, conversion

import { sendToBlender } from "../../blender-bridge.js";

export const greasePencilTools = [
  {
    name: "blender_gp_create",
    description:
      "Create a new Grease Pencil object in the scene. " +
      "The object is linked to the active collection and made active. " +
      "Returns the object name and its Grease Pencil data-block name. " +
      "Example call: { \"name\": \"Sketch\", \"location\": [0, 0, 0] }.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name for the new Grease Pencil object (default: 'GPencil').",
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "World-space [x, y, z] location for the object. " +
            "IMPORTANT: Must be a JSON array of 3 numbers, NOT a string. " +
            "Example: [0, 0, 0]. Default: [0, 0, 0].",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("gp/create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_gp_add_layer",
    description:
      "Add a new layer to an existing Grease Pencil object. " +
      "Layers act as separate drawing planes that can be shown/hidden and reordered. " +
      "Returns the layer name and index.",
    inputSchema: {
      type: "object",
      properties: {
        gp_name: {
          type: "string",
          description: "Name of the Grease Pencil object to add the layer to.",
        },
        layer_name: {
          type: "string",
          description: "Name for the new layer.",
        },
      },
      required: ["gp_name", "layer_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("gp/add-layer", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_gp_draw_stroke",
    description:
      "Draw a stroke on a specified Grease Pencil layer. " +
      "A frame is created at the current scene frame if one does not already exist. " +
      "Each point is an [x, y, z] world-space coordinate. " +
      "pressure controls brush thickness per point (0.0–1.0, default 1.0). " +
      "material_index selects which material slot to use for the stroke. " +
      "Returns the stroke index and point count.",
    inputSchema: {
      type: "object",
      properties: {
        gp_name: {
          type: "string",
          description: "Name of the Grease Pencil object.",
        },
        layer_name: {
          type: "string",
          description: "Name of the layer to draw on.",
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
            "List of [x, y, z] world-space positions for each stroke point. " +
            "IMPORTANT: Must be a JSON array of arrays, NOT a string. " +
            "Example: [[0, 0, 0], [1, 0, 0], [1, 1, 0]].",
        },
        pressure: {
          type: "array",
          items: { type: "number" },
          maxItems: 1000,
          description:
            "Optional per-point pressure values (0.0–1.0). " +
            "If omitted, full pressure (1.0) is used for all points.",
        },
        material_index: {
          type: "integer",
          description: "Material slot index to use for this stroke (default: 0).",
        },
      },
      required: ["gp_name", "layer_name", "points"],
    },
    handler: async (args) => {
      const result = await sendToBlender("gp/draw-stroke", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_gp_set_material",
    description:
      "Create or update a Grease Pencil material on the specified GP object. " +
      "If no material exists at the given index a new one is created and appended. " +
      "color sets the stroke RGBA (values 0.0–1.0). " +
      "fill_color sets the fill RGBA. " +
      "stroke_width sets the line thickness in pixels. " +
      "Returns the material name and its slot index.",
    inputSchema: {
      type: "object",
      properties: {
        gp_name: {
          type: "string",
          description: "Name of the Grease Pencil object.",
        },
        index: {
          type: "integer",
          description: "Material slot index to create or modify (0-based).",
        },
        color: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 4,
          description:
            "Stroke RGBA color as [r, g, b] or [r, g, b, a] with values 0.0-1.0. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [1.0, 0.0, 0.0, 1.0] (opaque red).",
        },
        fill_color: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 4,
          description:
            "Fill RGBA color as [r, g, b] or [r, g, b, a] with values 0.0-1.0. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [0.0, 0.0, 1.0, 0.5] (semi-transparent blue).",
        },
        stroke_width: {
          type: "number",
          description: "Stroke line width/thickness in pixels.",
        },
      },
      required: ["gp_name", "index"],
    },
    handler: async (args) => {
      const result = await sendToBlender("gp/set-material", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_gp_modifier_add",
    description:
      "Add a Grease Pencil modifier to the specified GP object. " +
      "Supported modifier types: SMOOTH, NOISE, THICKNESS, TINT, OFFSET, BUILD, SIMPLIFY. " +
      "Returns the modifier name and type added.",
    inputSchema: {
      type: "object",
      properties: {
        gp_name: {
          type: "string",
          description: "Name of the Grease Pencil object to add the modifier to.",
        },
        type: {
          type: "string",
          enum: ["SMOOTH", "NOISE", "THICKNESS", "TINT", "OFFSET", "BUILD", "SIMPLIFY"],
          description: "The type of Grease Pencil modifier to add. Must be UPPERCASE.",
        },
      },
      required: ["gp_name", "type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("gp/modifier-add", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_gp_to_curve",
    description:
      "Convert a Grease Pencil object into a Curve object. " +
      "The original GP object is replaced by a new Curve object in the scene. " +
      "Returns the name of the resulting curve object.",
    inputSchema: {
      type: "object",
      properties: {
        gp_name: {
          type: "string",
          description: "Name of the Grease Pencil object to convert.",
        },
      },
      required: ["gp_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("gp/to-curve", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_gp_to_mesh",
    description:
      "Convert a Grease Pencil object into a Mesh object. " +
      "The original GP object is replaced by a new Mesh object in the scene. " +
      "Returns the name of the resulting mesh object.",
    inputSchema: {
      type: "object",
      properties: {
        gp_name: {
          type: "string",
          description: "Name of the Grease Pencil object to convert.",
        },
      },
      required: ["gp_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("gp/to-mesh", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_gp_sculpt_stroke",
    description:
      "Apply a sculpt brush stroke to Grease Pencil strokes on the specified layer. " +
      "Supported brush types: SMOOTH, THICKNESS, STRENGTH, GRAB, PUSH, TWIST, PINCH, RANDOMIZE, CLONE. " +
      "params is a free-form object with brush settings such as radius, strength, and use_pressure. " +
      "Returns the brush type and params applied.",
    inputSchema: {
      type: "object",
      properties: {
        gp_name: {
          type: "string",
          description: "Name of the Grease Pencil object.",
        },
        layer_name: {
          type: "string",
          description: "Name of the layer whose strokes are to be sculpted.",
        },
        brush_type: {
          type: "string",
          enum: [
            "SMOOTH",
            "THICKNESS",
            "STRENGTH",
            "GRAB",
            "PUSH",
            "TWIST",
            "PINCH",
            "RANDOMIZE",
            "CLONE",
          ],
          description: "The GP sculpt brush type to use. Must be UPPERCASE.",
        },
        params: {
          type: "object",
          description:
            "Optional brush configuration. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Supported keys: radius (number), strength (number 0-1), use_pressure (boolean). " +
            "Example: { \"radius\": 50, \"strength\": 0.8, \"use_pressure\": true }.",
          additionalProperties: true,
        },
      },
      required: ["gp_name", "layer_name", "brush_type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("gp/sculpt-stroke", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
