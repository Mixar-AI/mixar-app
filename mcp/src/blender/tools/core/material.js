// Material tools — blender_material_list, blender_material_create,
//   blender_material_assign, blender_material_get_properties, blender_material_set_property

import { sendToBlender } from "../../blender-bridge.js";

export const materialTools = [
  {
    name: "blender_material_list",
    description:
      "List all materials in the current Blender file. " +
      "Returns: Array of { name, users, use_nodes, base_color }",
    inputSchema: {
      type: "object",
      properties: {},
    },
    handler: async () => {
      const result = await sendToBlender("material/list", {});
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_material_create",
    description:
      "Create a new material in Blender with optional Principled BSDF properties. " +
      "Automatically enables node-based shading and sets up a Principled BSDF node. " +
      "Example call: { \"name\": \"WoodMat\", \"base_color\": [0.4, 0.25, 0.1, 1.0], \"roughness\": 0.8, \"metallic\": 0.0 }. " +
      "Returns: { name, use_nodes, base_color, metallic, roughness }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name for the new material. Example: \"MetalChrome\".",
        },
        base_color: {
          type: "array",
          items: { type: "number" },
          minItems: 4,
          maxItems: 4,
          description:
            "Base color as a JSON array of exactly 4 numbers [r, g, b, a], each 0.0 to 1.0. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [0.8, 0.1, 0.1, 1.0] (red). Defaults to white [0.8, 0.8, 0.8, 1.0].",
        },
        metallic: {
          type: "number",
          description: "Metallic value, 0.0 (dielectric) to 1.0 (full metal). Example: 0.0.",
        },
        roughness: {
          type: "number",
          description: "Roughness value, 0.0 (mirror smooth) to 1.0 (fully rough). Example: 0.5.",
        },
        specular: {
          type: "number",
          description: "Specular IOR level, 0.0 to 1.0. Example: 0.5.",
        },
        emission_color: {
          type: "array",
          items: { type: "number" },
          minItems: 4,
          maxItems: 4,
          description:
            "Emission color as a JSON array of exactly 4 numbers [r, g, b, a], each 0.0 to 1.0. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [1.0, 0.5, 0.0, 1.0] (orange glow).",
        },
        emission_strength: {
          type: "number",
          description: "Emission strength multiplier. Example: 5.0 (bright glow).",
        },
        alpha: {
          type: "number",
          description: "Alpha (opacity) value, 0.0 (transparent) to 1.0 (opaque). Example: 1.0.",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("material/create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_material_assign",
    description:
      "Assign a material to an object. Optionally specify a material slot index. " +
      "If no slot is specified the material is appended as a new slot. " +
      "Example call: { \"object_name\": \"Cube\", \"material_name\": \"WoodMat\" }. " +
      "Returns: { object_name, material_name, slot }",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object to assign the material to. Example: \"Cube\".",
        },
        material_name: {
          type: "string",
          description: "Name of the material to assign. Example: \"WoodMat\".",
        },
        slot: {
          type: "integer",
          description: "Material slot index to assign into (0-based). Appends a new slot if omitted. Example: 0.",
        },
      },
      required: ["object_name", "material_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("material/assign", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_material_get_properties",
    description:
      "Get all Principled BSDF input properties for a named material. " +
      "Color inputs are returned as [r, g, b, a] arrays; scalar inputs as floats. " +
      "Returns: { name, properties: { [input_name]: value, ... } }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name of the material to inspect. Example: \"MetalChrome\".",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("material/get-properties", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_material_set_property",
    description:
      "Set a single Principled BSDF input property on a named material. " +
      "Use canonical 4.x input names such as 'Base Color', 'Metallic', 'Roughness', " +
      "'Emission Color', 'Emission Strength', 'Alpha', 'Coat Weight', etc. " +
      "Example for color: { \"name\": \"WoodMat\", \"property\": \"Base Color\", \"value\": [0.4, 0.25, 0.1, 1.0] }. " +
      "Example for scalar: { \"name\": \"WoodMat\", \"property\": \"Roughness\", \"value\": 0.8 }. " +
      "Returns: { name, property, value }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name of the material to modify. Example: \"WoodMat\".",
        },
        property: {
          type: "string",
          description:
            "Principled BSDF input name (case-sensitive). " +
            "Common values: \"Base Color\", \"Metallic\", \"Roughness\", \"Emission Color\", " +
            "\"Emission Strength\", \"Alpha\", \"Coat Weight\", \"IOR\". " +
            "Example: \"Roughness\".",
        },
        value: {
          oneOf: [
            { type: "number" },
            { type: "array", items: { type: "number" }, minItems: 4, maxItems: 4 },
          ],
          description:
            "New value for the property. For color inputs: a JSON array of 4 numbers [r, g, b, a]. " +
            "For scalar inputs: a single number. " +
            "IMPORTANT: Color arrays must be JSON arrays, NOT strings. " +
            "Correct: [0.8, 0.1, 0.1, 1.0] — Wrong: \"[0.8, 0.1, 0.1, 1.0]\".",
        },
      },
      required: ["name", "property", "value"],
    },
    handler: async (args) => {
      const result = await sendToBlender("material/set-property", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
